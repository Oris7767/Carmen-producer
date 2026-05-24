# 🪐 Carmen Prompt Generator Bot

Telegram bot tạo hàng loạt prompt ảnh (Banana/Imagen) + video (Veo/Kling) + lời thoại từ nội dung người dùng.

## Tính năng

- Paste nội dung → chọn số phân cảnh → chọn style → chọn AI model (Gemini/DeepSeek)
- 8 style presets: Stickman, 3D Pixar, Cổ trang, ASMR Vlog, Cinematic, Fantasy, Anime, Minimalist
- Xuất file `.txt` gồm prompt ảnh, prompt video, lời thoại cho từng phân cảnh

## Cài đặt

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Chạy local

```bash
# Tạo bot tại @BotFather, copy token vào .env
cp .env.example .env
# Sửa PROMPT_BOT_TOKEN, GEMINI_API_KEY, DEEPSEEK_API_KEY trong .env

python telegram_bot.py
```

## Deploy lên Render

1. Tạo **Background Worker** trên Render
2. Connect GitHub repo này
3. Start Command: `python telegram_bot.py`
4. Set Env Variables: `PROMPT_BOT_TOKEN`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`

## Flow

```
/start → paste nội dung → chọn #cảnh (3/5/7/10/15) → chọn style → chọn model → 📥 file .txt
```
