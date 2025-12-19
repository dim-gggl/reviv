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
echo 'KIE_API_KEY=your_token_here' >> .env
```
For Kie.ai, the source image URL must be publicly reachable. Configure S3 (recommended) by adding:
```bash
echo 'AWS_ACCESS_KEY_ID=...' >> .env
echo 'AWS_SECRET_ACCESS_KEY=...' >> .env
echo 'AWS_STORAGE_BUCKET_NAME=...' >> .env
echo 'AWS_S3_REGION_NAME=eu-north-1' >> .env
echo 'USE_S3_STORAGE=1' >> .env
echo 'AWS_QUERYSTRING_AUTH=0' >> .env
```
If your bucket is private, set `AWS_QUERYSTRING_AUTH=1` to generate presigned URLs (and optionally `AWS_QUERYSTRING_EXPIRE=3600`).
If you use an S3-compatible provider (R2/MinIO/Spaces), also set `AWS_S3_ENDPOINT_URL` and (optionally) `AWS_S3_ADDRESSING_STYLE`.
Alternative: if you expose your local Django instance on a public origin (e.g. using a tunnel), set `PUBLIC_MEDIA_BASE_URL` to that origin so relative media URLs become public.
Optional tuning:
```bash
echo 'KIE_ASPECT_RATIO=auto' >> .env
echo 'KIE_MODEL=nano-banana-pro' >> .env
echo 'KIE_STATUS_URL_TEMPLATE=https://api.kie.ai/api/v1/jobs/{task_id}' >> .env
```
If you get repeated 404s during polling, set:
```bash
echo 'KIE_STATUS_URL_TEMPLATES=https://api.kie.ai/api/v1/jobs/{task_id},https://api.kie.ai/api/v1/jobs/getTask?taskId={task_id},https://api.kie.ai/api/v1/jobs/{task_id}/status' >> .env
echo 'KIE_MAX_NOT_FOUND=10' >> .env
```

3. Run migrations:
```bash
source .venv/bin/activate
uv run manage.py migrate
```

4. Create a superuser (optional):
```bash
source .venv/bin/activate
uv run manage.py createsuperuser
```

5. Start the development server:
```bash
source .venv/bin/activate
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

The app uses Kie.ai's `nano-banana-pro` model for image enhancement with configurable parameters:
- Resolution: 2K
- Aspect ratio: Match input image
- Output format: PNG
