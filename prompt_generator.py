"""
AI Prompt Generator — supports Gemini and DeepSeek.
Generates structured scene-by-scene prompts for image (Banana/Imagen),
video (Veo), and dialogue from user content.
"""

import json
import re
import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

# Load env from same directory (local) or os.environ (Render)
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from styles import STYLES


@dataclass
class Scene:
    scene_number: int
    image_prompt: str
    video_prompt: str
    dialogue: str


@dataclass
class Script:
    title: str
    style: str
    num_scenes: int
    scenes: list = field(default_factory=list)

    def to_txt(self) -> str:
        """Format as downloadable .txt file."""
        style_label = STYLES.get(self.style, {}).get("label", self.style)
        lines = []
        lines.append("=" * 60)
        lines.append(f"KỊCH BẢN: {self.title}")
        lines.append(f"Style: {style_label}")
        lines.append(f"Số phân cảnh: {self.num_scenes}")
        lines.append("=" * 60)
        lines.append("")

        for scene in self.scenes:
            lines.append(f"{'─' * 40}")
            lines.append(f"🎬 PHÂN CẢNH {scene.scene_number}")
            lines.append(f"{'─' * 40}")
            lines.append("")
            lines.append("🎨 PROMPT ẢNH (Banana / Imagen):")
            lines.append(scene.image_prompt)
            lines.append("")
            lines.append("🎥 PROMPT VIDEO (Veo / Kling):")
            lines.append(scene.video_prompt)
            lines.append("")
            lines.append("🗣️ LỜI THOẠI / VOICEOVER:")
            lines.append(scene.dialogue)
            lines.append("")

        lines.append("=" * 60)
        lines.append("📋 HƯỚNG DẪN SỬ DỤNG:")
        lines.append("- Prompt ảnh: Paste vào Banana (Google Labs) hoặc Imagen")
        lines.append("- Prompt video: Paste vào Google Flow / Veo / Kling")
        lines.append("- Lời thoại: Dùng Google TTS hoặc ElevenLabs để tạo giọng đọc")
        lines.append("- Tỉ lệ khung hình khuyến nghị: 9:16 (dọc) cho Reels/Shorts/TikTok")
        lines.append("=" * 60)

        return "\n".join(lines)


def _build_gemini_prompt(content: str, num_scenes: int, style_key: str) -> str:
    """Build the full prompt for Gemini."""
    style_info = STYLES.get(style_key, STYLES["cinematic"])
    system_instruction = style_info["system_instruction"]
    style_label = style_info["label"]

    return f"""{system_instruction}

NHIỆM VỤ: Tạo kịch bản {num_scenes} phân cảnh dựa trên nội dung người dùng cung cấp.

NỘI DUNG NGƯỜI DÙNG:
---
{content}
---

YÊU CẦU OUTPUT (JSON format chính xác, không thêm bất kỳ text nào ngoài JSON):

{{
  "title": "Tiêu đề kịch bản (ngắn gọn, hấp dẫn, tiếng Việt)",
  "scenes": [
    {{
      "scene_number": 1,
      "image_prompt": "Mô tả chi tiết 1 khung hình tĩnh cho Banana/Imagen. Mô tả bố cục, ánh sáng, màu sắc, nhân vật, background. CUỐI CÙNG luôn thêm: 'photorealistic, cinematic lighting, 9:16 vertical aspect ratio, no text, no words, no watermark' nếu là ảnh thực tế; hoặc điều chỉnh phù hợp với style {style_label}. Viết bằng TIẾNG ANH để AI tạo ảnh hiểu tốt nhất.",
      "video_prompt": "Mô tả chuyển động trong phân cảnh này cho Veo/Video generator. Mô tả camera movement, animation, chuyển động nhân vật, thời gian. Viết bằng TIẾNG ANH. CUỐI CÙNG thêm: '9:16 vertical aspect ratio, smooth motion, no text overlay'.",
      "dialogue": "Lời thoại hoặc voiceover cho phân cảnh này. Viết bằng TIẾNG VIỆT, tự nhiên, cảm xúc. Có thể là độc thoại nội tâm, lời dẫn truyện, hoặc hội thoại."
    }}
  ]
}}

QUAN TRỌNG:
- Mỗi image_prompt và video_prompt phải mô tả chi tiết, cụ thể — không chung chung
- Image prompt dành cho AI tạo ẢNH TĨNH nên phải mô tả 1 KHOẢNH KHẮC duy nhất
- Video prompt dành cho AI tạo VIDEO nên mô tả CHUYỂN ĐỘNG trong phân cảnh
- Dialogue viết bằng tiếng Việt tự nhiên, phù hợp văn hoá Việt Nam
- Giữ đúng phong cách {style_label}
- Output CHỈ có JSON, không kèm markdown code block"""


def _build_deepseek_prompt(content: str, num_scenes: int, style_key: str) -> str:
    """Build the full prompt for DeepSeek (same structure, optimized for DeepSeek)."""
    # DeepSeek uses the same prompt structure
    return _build_gemini_prompt(content, num_scenes, style_key)


def generate_with_gemini(content: str, num_scenes: int, style_key: str) -> Script:
    """Generate script using Google Gemini API."""
    import google.generativeai as genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in .env")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config={
            "temperature": 0.9,
            "top_p": 0.95,
            "max_output_tokens": 8192,
        },
    )

    prompt = _build_gemini_prompt(content, num_scenes, style_key)
    response = model.generate_content(prompt)
    text = response.text.strip()

    # Parse JSON from response (handle markdown code blocks)
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    data = json.loads(text)
    return _parse_script(data, style_key)


def generate_with_deepseek(content: str, num_scenes: int, style_key: str) -> Script:
    """Generate script using DeepSeek API (OpenAI-compatible)."""
    from openai import OpenAI

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY not found in .env")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    prompt = _build_deepseek_prompt(content, num_scenes, style_key)

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "You are a professional screenwriter and prompt engineer. Output ONLY valid JSON, no markdown, no extra text."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.9,
        max_tokens=8192,
    )

    text = response.choices[0].message.content.strip()

    # Parse JSON from response
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    data = json.loads(text)
    return _parse_script(data, style_key)


def _parse_script(data: dict, style_key: str) -> Script:
    """Parse JSON response into Script dataclass."""
    scenes = []
    for s in data.get("scenes", []):
        scenes.append(Scene(
            scene_number=s["scene_number"],
            image_prompt=s.get("image_prompt", ""),
            video_prompt=s.get("video_prompt", ""),
            dialogue=s.get("dialogue", ""),
        ))

    return Script(
        title=data.get("title", "Untitled"),
        style=style_key,
        num_scenes=len(scenes),
        scenes=scenes,
    )


def generate(content: str, num_scenes: int, style_key: str, model: str = "gemini") -> Script:
    """Main entry point — route to correct generator."""
    if model == "deepseek":
        return generate_with_deepseek(content, num_scenes, style_key)
    else:
        return generate_with_gemini(content, num_scenes, style_key)
