from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image

from const import PROMPT

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)


def google_nano_generate_image(prompt, image_path="", output_path="generated_image.png"):
    if not prompt:
		prompt = PROMPT
	
	if not image_path:
		raise ValueError("An input image is required")

    image = Image.open(image_path)

	response = client.models.generate_content(
	    model="gemini-3-pro-image-preview",
	    contents=[prompt, image],
	)

    for part in response.parts:
        if part.text:
            print(part.text)
        elif part.inline_data:
            image = part.as_image()
            image.save(output_path)
	
	print(f"Image saved to {output_path}")


if __name__ == "__main__":
	prompt = input("Prompt >>>").strip() or PROMPT
	image_path = input("Image Path >>>").strip()
	output_path = input("Output Path >>>").strip() or "generated_image.png"	

	google_nano_generate_image(prompt, image_path, output_path)