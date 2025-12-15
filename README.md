# Reviv - Django Web Interface

A web interface for restoring old, low-quality images using nano banana API.

## Setup

1. Install dependencies:
```bash
uv venv
uv sync
```

2. Set up environment variables:
Create a `.env` file in the root directory with:
```bash
touch .env
echo 'REPLICATE_API_TOKEN=your_token_here' >> .env
```

3. Run migrations:
```bash
cd reviv
uv run manage.py migrate
```

4. Create a superuser (optional):
```bash
uv run manage.py createsuperuser
```

5. Start the development server:
```bash
uv run manage.py runserver
```

6. Visit http://localhost:8000 to use the application

## Project Structure

```
reviv/
├── config/          # Django project settings
├── reviv/           # Main application
│   ├── models.py    # PhotoRestoration model
│   ├── views.py     # View handlers
│   ├── services.py  # Image enhancement service
│   ├── templates/   # HTML templates
│   └── const.py     # Default prompt
├── media/           # User uploaded and enhanced images
└── static/          # Static files
```

## Usage

1. Signup/login
2. upload an image
3. Download the result

## API Integration

The app uses Replicate's `google/nano-banana-pro` model for image enhancement with configurable parameters:
- Resolution: 2K
- Aspect ratio: Match input image
- Output format: PNG
- Safety filter: Block only high-risk content
