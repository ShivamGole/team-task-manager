# Team Task Manager - Flask Full Stack

A Flask full-stack web app where users can create projects, manage team members, assign tasks, and track progress with role-based access control.

## Features

- Signup/Login authentication
- Admin and Member roles
- Project creation and project member management
- Task creation, assignment, priority, due date and status tracking
- Dashboard with total tasks, status counts and overdue tasks
- REST APIs with validation
- SQL database relationships using Flask-SQLAlchemy
- Railway-ready deployment files

## Tech Stack

- Python Flask
- Flask-SQLAlchemy
- SQLite locally
- PostgreSQL supported on Railway using `DATABASE_URL`
- HTML/CSS templates
- Gunicorn for production

## Local Setup

```bash
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate  # Mac/Linux

pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Railway Deployment

1. Push this project to GitHub.
2. Go to Railway and create a new project from your GitHub repo.
3. Add a PostgreSQL database in Railway.
4. Railway will automatically provide `DATABASE_URL`.
5. Add this variable in Railway:

```text
SECRET_KEY=your-production-secret
```

<!-- 6. Deploy. Railway will use: -->

```text
gunicorn app:app
```

## REST API Endpoints

### Auth

```http
POST /api/auth/signup
POST /api/auth/login
POST /api/auth/logout
GET /api/auth/me
```

### Users

```http
GET /api/users
```

Admin only: list all registered users.

### Projects

```http
GET /api/projects
POST /api/projects
GET /api/projects/<project_id>
PATCH /api/projects/<project_id>
DELETE /api/projects/<project_id>
GET /api/projects/<project_id>/members
POST /api/projects/<project_id>/members
DELETE /api/projects/<project_id>/members
GET /api/projects/<project_id>/tasks
```

Example create project JSON:

```json
{
  "name": "Website Redesign",
  "description": "Client landing page revamp"
}
```

### Tasks

```http
GET /api/tasks
POST /api/tasks
PATCH /api/tasks/<task_id>
DELETE /api/tasks/<task_id>
```

Example create task JSON:

```json
{
  "title": "Create login page",
  "description": "Build UI and validation",
  "project_id": 1,
  "assignee_id": 2,
  "status": "Todo",
  "priority": "High",
  "due_date": "2026-05-20"
}
```

Valid task statuses:

- Todo
- In Progress
- Done

Valid priorities:

- Low
- Medium
- High

## UI Features

- Create and delete projects
- Add and remove project members
- Create tasks with assignee, priority, due date, and status
- Update task status directly from the task list
- Delete tasks by creator or admin
- Dashboard shows project/task summary and overdue counts

## Role Rules

- Admin can view and manage all projects, members, and tasks.
- Member can view assigned or owned projects and their tasks.
- Project owner or admin can add/remove project members.
- Task creator or admin can delete a task.

## Submission Checklist

- Live Railway URL: <PASTE_LIVE_URL_HERE>
- GitHub repository URL: <PASTE_GITHUB_REPO_URL_HERE>
- README file (this file)
- Fully functional app (deployed + working)

## Railway Setup Notes (for successful deploy)

- Railway provides `DATABASE_URL` automatically when you add the PostgreSQL database.
- Set `SECRET_KEY` in Railway environment variables.
- The app uses Flask-SQLAlchemy models and runs `db.create_all()` at startup, so tables will be created automatically on first deploy.
- Deployment uses Gunicorn: `gunicorn app:app` (configured via `Procfile` / `railway.json`).
