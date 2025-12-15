# Reviv - Django Web Interface

A beautiful web interface for restoring old, low-quality images using the nano banana API.

## Features

- **Elegant Editorial Design** - Refined magazine-style aesthetics with vintage photography studio inspiration
- **Drag & Drop Upload** - Easy image upload with preview
- **Before/After Comparison** - Interactive slider to compare original and restored images
- **Gallery View** - Showcase of all restored memories
- **Responsive Design** - Works beautifully on all devices

## Setup

1. Install dependencies:
```bash
source .venv/bin/activate
uv pip install django pillow replicate python-dotenv
```

2. Set up environment variables:
Create a `.env` file in the root directory with:
```
REPLICATE_API_TOKEN=your_token_here
```

3. Run migrations:
```bash
cd config
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
config/
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

1. Navigate to the home page
2. Upload an old or damaged photo
3. Optionally customize the restoration prompt
4. Click "Restore Photo" and wait for processing
5. View the before/after comparison with an interactive slider
6. Download the restored image

## Design Philosophy

The interface combines:
- **Typography**: Crimson Pro (serif) for elegance + Epilogue (sans) for clarity
- **Color Palette**: Warm sepia tones, deep charcoal, cream backgrounds
- **Textures**: Subtle film grain and paper texture overlays
- **Animations**: Smooth, sophisticated transitions
- **Layout**: Asymmetric, editorial-style with generous whitespace

## API Integration

The app uses Replicate's `google/nano-banana-pro` model for image enhancement with configurable parameters:
- Resolution: 2K
- Aspect ratio: Match input image
- Output format: PNG
- Safety filter: Block only high-risk content
