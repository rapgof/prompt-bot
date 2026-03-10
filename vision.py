import os
import base64
import logging
import httpx

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


async def extract_text_from_image(image_bytes: bytes) -> str:
    """
    Extract text/prompt from an image using Claude Vision API.
    Returns the extracted text or empty string on failure.
    """
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set, skipping OCR")
        return ""

    try:
        image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

        payload = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_b64
                            }
                        },
                        {
                            "type": "text",
                            "text": (
                                "This image likely contains an AI image generation prompt or text. "
                                "Please extract ALL text you can see in this image. "
                                "Return ONLY the extracted text, nothing else. "
                                "If there are multiple text blocks, separate them with newlines. "
                                "Do not add any explanations or commentary."
                            )
                        }
                    ]
                }
            ]
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json=payload
            )
            response.raise_for_status()
            data = response.json()

        extracted = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                extracted += block.get("text", "")

        logger.info(f"Extracted text length: {len(extracted)}")
        return extracted.strip()

    except Exception as e:
        logger.error(f"Vision API error: {e}")
        return ""
