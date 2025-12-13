from dotenv import load_dotenv
import replicate

from const import PROMPT

load_dotenv()

def replicate_generate_image(prompt, 
				             resolution="2K", 
				             image_input=[], 
				             aspect_ratio="match_input_image", 
				             output_format="png", 
				             safety_filter_level="block_only_high",
				             output_file_path="my-image.png"):
    if not prompt:
        prompt = PROMPT
    if not image_input:
        raise ValueError("An input image is required")

    output = replicate.run(
        "google/nano-banana-pro",
        input={
            "prompt": prompt,
            "resolution": resolution,
            "image_input": image_input,
            "aspect_ratio": aspect_ratio,
            "output_format": output_format,
            "safety_filter_level": safety_filter_level
        }
    )

    with open(output_file_path, "wb") as file:
        file.write(output.read())
    
    print(f"Image saved to {output_file_path}")

    return output.url


if __name__ == "__main__":
    prompt = input("Prompt >>>").strip() or PROMPT
    resolution = input("Resolution >>>").strip() or "2K"
    image_input_path = input("Image Input (file path or URL) >>>").strip()
    if image_input_path.startswith("'"):
        
    
    # Check if it's a URL or a local file
    if image_input_path.startswith(('http://', 'https://')):
        image_input = [image_input_path]
    else:
        # For local files, open them as file objects
        image_input = [open(image_input_path, "rb")]
    
    aspect_ratio = input("Aspect Ratio >>>").strip() or "match_input_image"
    output_format = input("Output Format >>>").strip() or "png"
    safety_filter_level = input("Safety Filter Level >>>").strip() or "block_only_high"
    output_file_path = input("Output File Path >>>").strip() or "generated_image.png"

    image_url = replicate_generate_image(prompt, resolution, image_input, aspect_ratio, output_format, safety_filter_level, output_file_path)
    print(f"Image URL: {image_url}")
