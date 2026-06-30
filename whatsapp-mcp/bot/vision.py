import base64
import mimetypes

def encode_image(image_path: str) -> str | None:
    try:
        with open(image_path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode('utf-8')
            mime_type, _ = mimetypes.guess_type(image_path)
            if not mime_type:
                mime_type = "image/jpeg"
            return f"data:{mime_type};base64,{encoded}"
    except Exception as e:
        print(f"[Vision error] Could not encode {image_path}: {e}")
        return None
