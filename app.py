import os
from datetime import datetime, date
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-me')

# Railway/Postgres provides DATABASE_URL. Use it when present.
database_url = os.getenv('DATABASE_URL')
if database_url:
    # Some providers use postgres://; SQLAlchemy expects postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # Local fallback
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///team_task_manager.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='Member')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owned_projects = db.relationship('Project', backref='owner', lazy=True)
    assigned_tasks = db.relationship('Task', backref='assignee', lazy=True, foreign_keys='Task.assignee_id')

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'email': self.email, 'role': self.role}

class ProjectMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User')
    __table_args__ = (db.UniqueConstraint('project_id', 'user_id', name='unique_project_user'),)

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, default='')
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    members = db.relationship('ProjectMember', backref='project', lazy=True, cascade='all, delete-orphan')
    tasks = db.relationship('Task', backref='project', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'owner_id': self.owner_id,
            'owner': self.owner.name,
            'members': [m.user.to_dict() for m in self.members],
            'task_count': len(self.tasks),
        }

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, default='')
    status = db.Column(db.String(30), nullable=False, default='Todo')
    priority = db.Column(db.String(20), nullable=False, default='Medium')
    due_date = db.Column(db.Date, nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    assignee_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    creator = db.relationship('User', foreign_keys=[created_by_id])

    def is_overdue(self):
        return self.due_date is not None and self.due_date < date.today() and self.status != 'Done'

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'status': self.status,
            'priority': self.priority,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'overdue': self.is_overdue(),
            'project_id': self.project_id,
            'project': self.project.name,
            'assignee': self.assignee.to_dict() if self.assignee else None,
            'created_by': self.creator.name,
        }

VALID_STATUSES = {'Todo', 'In Progress', 'Done'}
VALID_PRIORITIES = {'Low', 'Medium', 'High'}
VALID_ROLES = {'Admin', 'Member'}

def current_user():
    user_id = session.get('user_id')
    return User.query.get(user_id) if user_id else None

@app.context_processor
def inject_user():
    return {'current_user': current_user()}

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash('Please login first.', 'error')
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or user.role != 'Admin':
            flash('Admin access required.', 'error')
            return redirect(url_for('dashboard'))
        return view(*args, **kwargs)
    return wrapped

def api_user_required():
    user = current_user()
    if not user:
        return None, (jsonify({'error': 'Authentication required'}), 401)
    return user, None

def can_access_project(user, project):
    if user.role == 'Admin' or project.owner_id == user.id:
        return True
    return ProjectMember.query.filter_by(project_id=project.id, user_id=user.id).first() is not None

def get_accessible_projects(user):
    if user.role == 'Admin':
        return Project.query.order_by(Project.created_at.desc()).all()
    project_ids = [m.project_id for m in ProjectMember.query.filter_by(user_id=user.id).all()]
    return Project.query.filter((Project.owner_id == user.id) | (Project.id.in_(project_ids))).order_by(Project.created_at.desc()).all()

def parse_due_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        raise ValueError('due_date must be YYYY-MM-DD')

@app.route('/')
def home():
    return redirect(url_for('dashboard') if current_user() else url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        role = request.form.get('role', 'Member')
        if not name or not email or len(password) < 6 or role not in VALID_ROLES:
            flash('Enter valid details. Password must be at least 6 characters.', 'error')
            return render_template('signup.html')
        if User.query.filter_by(email=email).first():
            flash('Email already exists.', 'error')
            return render_template('signup.html')
        user = User(name=name, email=email, password_hash=generate_password_hash(password), role=role)
        db.session.add(user)
        db.session.commit()
        session['user_id'] = user.id
        return redirect(url_for('dashboard'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash('Invalid email or password.', 'error')
            return render_template('login.html')
        session['user_id'] = user.id
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user()
    if user.role == 'Admin':
        projects = Project.query.order_by(Project.created_at.desc()).all()
        tasks = Task.query.order_by(Task.created_at.desc()).all()
    else:
        project_ids = [m.project_id for m in ProjectMember.query.filter_by(user_id=user.id).all()]
        projects = Project.query.filter((Project.owner_id == user.id) | (Project.id.in_(project_ids))).all()
        tasks = Task.query.filter((Task.assignee_id == user.id) | (Task.created_by_id == user.id)).order_by(Task.created_at.desc()).all()
    stats = {
        'projects': len(projects),
        'tasks': len(tasks),
        'todo': sum(1 for t in tasks if t.status == 'Todo'),
        'progress': sum(1 for t in tasks if t.status == 'In Progress'),
        'done': sum(1 for t in tasks if t.status == 'Done'),
        'overdue': sum(1 for t in tasks if t.is_overdue()),
    }
    return render_template('dashboard.html', projects=projects, tasks=tasks, stats=stats)

@app.route('/projects')
@login_required
def projects_page():
    user = current_user()
    projects = get_accessible_projects(user)
    users = User.query.all()
    return render_template('projects.html', projects=projects, users=users)

@app.route('/tasks')
@login_required
def tasks_page():
    user = current_user()
    projects = get_accessible_projects(user)
    users = User.query.all()
    tasks = Task.query.all() if user.role == 'Admin' else Task.query.filter((Task.assignee_id == user.id) | (Task.created_by_id == user.id)).all()
    return render_template('tasks.html', projects=projects, users=users, tasks=tasks)

# REST APIs
@app.route('/api/auth/me')
def api_me():
    user, err = api_user_required()
    if err: return err
    return jsonify(user.to_dict())

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or request.form
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'error': 'Invalid email or password'}), 401
    session['user_id'] = user.id
    return jsonify(user.to_dict())

@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'message': 'Logged out'})

@app.route('/api/auth/signup', methods=['POST'])
def api_signup():
    data = request.get_json(silent=True) or request.form
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    role = data.get('role', 'Member')
    if not name or not email or len(password) < 6 or role not in VALID_ROLES:
        return jsonify({'error': 'Enter valid details. Password must be at least 6 characters.'}), 422
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already exists.'}), 422
    user = User(name=name, email=email, password_hash=generate_password_hash(password), role=role)
    db.session.add(user)
    db.session.commit()
    session['user_id'] = user.id
    return jsonify(user.to_dict()), 201

@app.route('/api/users', methods=['GET'])
def api_users():
    user, err = api_user_required()
    if err: return err
    if user.role != 'Admin':
        return jsonify({'error': 'Only admin can list users'}), 403
    return jsonify([u.to_dict() for u in User.query.order_by(User.name).all()])

@app.route('/api/projects', methods=['GET', 'POST'])
def api_projects():
    user, err = api_user_required()
    if err: return err
    if request.method == 'GET':
        if user.role == 'Admin':
            projects = Project.query.all()
        else:
            project_ids = [m.project_id for m in ProjectMember.query.filter_by(user_id=user.id).all()]
            projects = Project.query.filter((Project.owner_id == user.id) | (Project.id.in_(project_ids))).all()
        return jsonify([p.to_dict() for p in projects])
    data = request.get_json(silent=True) or request.form
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Project name is required'}), 422
    project = Project(name=name, description=data.get('description', ''), owner_id=user.id)
    db.session.add(project)
    db.session.commit()
    db.session.add(ProjectMember(project_id=project.id, user_id=user.id))
    db.session.commit()
    return jsonify(project.to_dict()), 201

@app.route('/api/projects/<int:project_id>/members', methods=['POST'])
def api_add_member(project_id):
    user, err = api_user_required()
    if err: return err
    project = Project.query.get_or_404(project_id)
    if user.role != 'Admin' and project.owner_id != user.id:
        return jsonify({'error': 'Only admin or project owner can add members'}), 403
    data = request.get_json(silent=True) or request.form
    member = User.query.get(data.get('user_id'))
    if not member:
        return jsonify({'error': 'Valid user_id is required'}), 422
    if not ProjectMember.query.filter_by(project_id=project.id, user_id=member.id).first():
        db.session.add(ProjectMember(project_id=project.id, user_id=member.id))
        db.session.commit()
    return jsonify(project.to_dict())

@app.route('/api/projects/<int:project_id>', methods=['GET', 'PATCH', 'DELETE'])
def api_project_detail(project_id):
    user, err = api_user_required()
    if err: return err
    project = Project.query.get_or_404(project_id)
    if not can_access_project(user, project):
        return jsonify({'error': 'No access to this project'}), 403

    if request.method == 'GET':
        return jsonify(project.to_dict())

    if request.method == 'DELETE':
        if user.role != 'Admin' and project.owner_id != user.id:
            return jsonify({'error': 'Only admin or owner can delete project'}), 403
        db.session.delete(project)
        db.session.commit()
        return jsonify({'message': 'Project deleted'})

    data = request.get_json(silent=True) or request.form
    if 'name' in data:
        project.name = data.get('name', project.name).strip() or project.name
    if 'description' in data:
        project.description = data.get('description', project.description)
    db.session.commit()
    return jsonify(project.to_dict())

@app.route('/api/projects/<int:project_id>/members', methods=['GET', 'DELETE'])
def api_project_members(project_id):
    user, err = api_user_required()
    if err: return err
    project = Project.query.get_or_404(project_id)
    if user.role != 'Admin' and project.owner_id != user.id:
        return jsonify({'error': 'Only admin or owner can manage members'}), 403

    if request.method == 'GET':
        return jsonify([m.user.to_dict() for m in project.members])

    data = request.get_json(silent=True) or request.form
    member_id = data.get('user_id')
    if not member_id:
        return jsonify({'error': 'user_id is required to remove a member'}), 422
    membership = ProjectMember.query.filter_by(project_id=project.id, user_id=member_id).first()
    if not membership:
        return jsonify({'error': 'Membership not found'}), 404
    db.session.delete(membership)
    db.session.commit()
    return jsonify({'message': 'Member removed', 'project': project.to_dict()})

@app.route('/api/projects/<int:project_id>/tasks', methods=['GET'])
def api_project_tasks(project_id):
    user, err = api_user_required()
    if err: return err
    project = Project.query.get_or_404(project_id)
    if not can_access_project(user, project):
        return jsonify({'error': 'No access to this project'}), 403
    return jsonify([t.to_dict() for t in project.tasks])

@app.route('/api/tasks', methods=['GET', 'POST'])
def api_tasks():
    user, err = api_user_required()
    if err: return err
    if request.method == 'GET':
        tasks = Task.query.all() if user.role == 'Admin' else Task.query.filter((Task.assignee_id == user.id) | (Task.created_by_id == user.id)).all()
        return jsonify([t.to_dict() for t in tasks])
    data = request.get_json(silent=True) or request.form
    title = data.get('title', '').strip()
    project = Project.query.get(data.get('project_id'))
    if not title or not project:
        return jsonify({'error': 'title and project_id are required'}), 422
    if not can_access_project(user, project):
        return jsonify({'error': 'No access to this project'}), 403
    status = data.get('status', 'Todo')
    priority = data.get('priority', 'Medium')
    if status not in VALID_STATUSES or priority not in VALID_PRIORITIES:
        return jsonify({'error': 'Invalid status or priority'}), 422
    try:
        due_date = parse_due_date(data.get('due_date'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 422
    assignee_id = data.get('assignee_id') or None
    if assignee_id and not User.query.get(assignee_id):
        return jsonify({'error': 'Invalid assignee_id'}), 422
    task = Task(title=title, description=data.get('description', ''), status=status, priority=priority,
                due_date=due_date, project_id=project.id, assignee_id=assignee_id, created_by_id=user.id)
    db.session.add(task)
    db.session.commit()
    return jsonify(task.to_dict()), 201

@app.route('/api/tasks/<int:task_id>', methods=['PATCH', 'DELETE'])
def api_task_detail(task_id):
    user, err = api_user_required()
    if err: return err
    task = Task.query.get_or_404(task_id)
    if user.role != 'Admin' and task.created_by_id != user.id and task.assignee_id != user.id:
        return jsonify({'error': 'No access to this task'}), 403
    if request.method == 'DELETE':
        if user.role != 'Admin' and task.created_by_id != user.id:
            return jsonify({'error': 'Only admin or creator can delete task'}), 403
        db.session.delete(task)
        db.session.commit()
        return jsonify({'message': 'Task deleted'})
    data = request.get_json(silent=True) or request.form
    for field in ['title', 'description']:
        if field in data:
            setattr(task, field, data.get(field))
    if 'status' in data:
        if data.get('status') not in VALID_STATUSES:
            return jsonify({'error': 'Invalid status'}), 422
        task.status = data.get('status')
    if 'priority' in data:
        if data.get('priority') not in VALID_PRIORITIES:
            return jsonify({'error': 'Invalid priority'}), 422
        task.priority = data.get('priority')
    if 'due_date' in data:
        try:
            task.due_date = parse_due_date(data.get('due_date'))
        except ValueError as e:
            return jsonify({'error': str(e)}), 422
    if 'assignee_id' in data:
        task.assignee_id = data.get('assignee_id') or None
    db.session.commit()
    return jsonify(task.to_dict())

# Form wrappers
@app.route('/projects/create', methods=['POST'])
@login_required
def create_project_form():
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    if not name:
        flash('Project name is required.', 'error')
        return redirect(url_for('projects_page'))
    user = current_user()
    project = Project(name=name, description=description, owner_id=user.id)
    db.session.add(project)
    db.session.commit()
    db.session.add(ProjectMember(project_id=project.id, user_id=user.id))
    db.session.commit()
    flash('Project created successfully.', 'success')
    return redirect(url_for('projects_page'))

@app.route('/projects/<int:project_id>/members/add', methods=['POST'])
@login_required
def add_member_form(project_id):
    user = current_user()
    project = Project.query.get_or_404(project_id)
    if user.role != 'Admin' and project.owner_id != user.id:
        flash('Only the project owner or admin can add members.', 'error')
        return redirect(url_for('projects_page'))
    member_id = request.form.get('user_id')
    member = User.query.get(member_id)
    if not member:
        flash('Select a valid user to add.', 'error')
        return redirect(url_for('projects_page'))
    if ProjectMember.query.filter_by(project_id=project.id, user_id=member.id).first():
        flash('User is already a member of this project.', 'error')
        return redirect(url_for('projects_page'))
    db.session.add(ProjectMember(project_id=project.id, user_id=member.id))
    db.session.commit()
    flash(f'{member.name} added to project.', 'success')
    return redirect(url_for('projects_page'))

@app.route('/projects/<int:project_id>/members/<int:user_id>/remove', methods=['POST'])
@login_required
def remove_member_form(project_id, user_id):
    user = current_user()
    project = Project.query.get_or_404(project_id)
    if user.role != 'Admin' and project.owner_id != user.id:
        flash('Only the project owner or admin can remove members.', 'error')
        return redirect(url_for('projects_page'))
    if project.owner_id == user_id:
        flash('Cannot remove the project owner.', 'error')
        return redirect(url_for('projects_page'))
    membership = ProjectMember.query.filter_by(project_id=project.id, user_id=user_id).first()
    if not membership:
        flash('Member not found.', 'error')
        return redirect(url_for('projects_page'))
    db.session.delete(membership)
    db.session.commit()
    flash('Member removed from project.', 'success')
    return redirect(url_for('projects_page'))

@app.route('/projects/<int:project_id>/delete', methods=['POST'])
@login_required
def delete_project_form(project_id):
    user = current_user()
    project = Project.query.get_or_404(project_id)
    if user.role != 'Admin' and project.owner_id != user.id:
        flash('Only the project owner or admin can delete this project.', 'error')
        return redirect(url_for('projects_page'))
    db.session.delete(project)
    db.session.commit()
    flash('Project deleted successfully.', 'success')
    return redirect(url_for('projects_page'))

@app.route('/tasks/create', methods=['POST'])
@login_required
def create_task_form():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    project_id = request.form.get('project_id')
    assignee_id = request.form.get('assignee_id') or None
    priority = request.form.get('priority', 'Medium')
    due_date_value = request.form.get('due_date')
    status = request.form.get('status', 'Todo')
    if not title or not project_id:
        flash('Task title and project are required.', 'error')
        return redirect(url_for('tasks_page'))
    project = Project.query.get(project_id)
    user = current_user()
    if not project or not can_access_project(user, project):
        flash('Invalid project selection.', 'error')
        return redirect(url_for('tasks_page'))
    if status not in VALID_STATUSES or priority not in VALID_PRIORITIES:
        flash('Invalid task status or priority.', 'error')
        return redirect(url_for('tasks_page'))
    try:
        due_date = parse_due_date(due_date_value)
    except ValueError as e:
        flash(str(e), 'error')
        return redirect(url_for('tasks_page'))
    if assignee_id and not User.query.get(assignee_id):
        flash('Invalid assignee selected.', 'error')
        return redirect(url_for('tasks_page'))
    task = Task(title=title, description=description, status=status, priority=priority,
                due_date=due_date, project_id=project.id,
                assignee_id=assignee_id, created_by_id=user.id)
    db.session.add(task)
    db.session.commit()
    flash('Task created successfully.', 'success')
    return redirect(url_for('tasks_page'))

@app.route('/tasks/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task_form(task_id):
    user = current_user()
    task = Task.query.get_or_404(task_id)
    if user.role != 'Admin' and task.created_by_id != user.id:
        flash('Only the task creator or admin can delete this task.', 'error')
        return redirect(url_for('tasks_page'))
    db.session.delete(task)
    db.session.commit()
    flash('Task deleted successfully.', 'success')
    return redirect(url_for('tasks_page'))

@app.route('/tasks/<int:task_id>/status', methods=['POST'])
@login_required
def update_task_status_form(task_id):
    task = Task.query.get_or_404(task_id)
    user = current_user()
    if user.role == 'Admin' or task.created_by_id == user.id or task.assignee_id == user.id:
        status = request.form.get('status')
        if status in VALID_STATUSES:
            task.status = status
            db.session.commit()
    return redirect(request.referrer or url_for('tasks_page'))

@app.cli.command('init-db')
def init_db_command():
    db.create_all()
    print('Database initialized.')

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
