import os
import cv2
import pytesseract
import re
import numpy as np
from PIL import Image, ImageDraw
from pdf2image import convert_from_path
from docx import Document
import gradio as gr
import traceback
import shutil
from datetime import datetime

pytesseract.pytesseract.tesseract_cmd = shutil.which("tesseract")

def convert_to_images(filepath):
    images = []
    ext = os.path.splitext(filepath)[1].lower()
    try:
        if ext == ".pdf":
            pages = convert_from_path(filepath)
            images.extend([page.convert("RGB") for page in pages])
        elif ext == ".docx":
            doc = Document(filepath)
            text = "\n".join([para.text for para in doc.paragraphs]).strip()
            img = Image.new("RGB", (1200, 1600), color="white")
            draw = ImageDraw.Draw(img)
            draw.text((10, 10), text[:4000], fill="black")
            images.append(img)
        else:
            img = Image.open(filepath).convert("RGB")
            images.append(img)
    except Exception as e:
        print(f"❌ Conversion error: {e}")
        img = Image.new("RGB", (800, 200), "white")
        draw = ImageDraw.Draw(img)
        draw.text((10, 90), f"File error: {e}", fill="red")
        images.append(img)
    return images

def blur_sensitive_text(pil_img):
    np_img = np.array(pil_img)
    img = cv2.cvtColor(np_img, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)
    altered = False

    patterns = [
        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",  # Email
        r"\b\d{10}\b",                                     # Phone
        r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4,6}\b",               # Card
        r"\b\d{5,}\b",                                     # Long numbers (Enrollment No, txn, etc.)
        r"\b\d{4}\s\d{4}\s\d{4}\b",                        # Aadhaar
        r"\b[A-Z]{5}\d{4}[A-Z]\b",                         # PAN
        r"(?i)(rcpt|txn|order|ref|payment|utr)[^\s]{3,}",  # References
    ]

    for i, word in enumerate(data['text']):
        try:
            if int(data['conf'][i]) < 60:
                continue
        except:
            continue

        word_clean = word.strip()
        normalized = word_clean.replace(" ", "").replace("-", "")
        for pattern in patterns:
            if re.fullmatch(pattern, normalized) or re.fullmatch(pattern, word_clean, re.IGNORECASE):
                x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                cv2.rectangle(img, (x, y), (x + w, y + h), (0, 0, 0), -1)
                altered = True
                break

    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB), altered

def blur_faces(np_img):
    img = np_img.copy()
    altered = False
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.1, 5)
    for (x, y, w, h) in faces:
        img[y:y+h, x:x+w] = cv2.GaussianBlur(img[y:y+h, x:x+w], (51, 51), 30)
        altered = True
    return img, altered

def redact_document(filepath):
    try:
        pages = convert_to_images(filepath)
        redacted_pages = []
        for page in pages:
            redacted_img, text_altered = blur_sensitive_text(page)
            final_img, face_altered = blur_faces(redacted_img)

            if not text_altered and not face_altered:
                cv2.putText(final_img, "✅ No sensitive info found", (50, 100),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)

            redacted_pages.append(Image.fromarray(final_img))

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_pdf = f"/tmp/redacted_{ts}.pdf"
        redacted_pages[0].save(output_pdf, save_all=True, append_images=redacted_pages[1:])
        return redacted_pages, output_pdf

    except Exception as e:
        print("❌ Error:", traceback.format_exc())
        img = Image.new("RGB", (800, 200), "white")
        draw = ImageDraw.Draw(img)
        draw.text((10, 90), f"Error: {e}", fill="red")
        fallback = f"/tmp/error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        img.save(fallback)
        return [img], fallback

iface = gr.Interface(
    fn=redact_document,
    inputs=gr.File(label="Upload image, PDF, or DOCX", type="filepath"),
    outputs=[
        gr.Gallery(label="Redacted Preview", columns=1),
        gr.File(label="Download Redacted PDF")
    ],
    title="🔐 Smart Doc Redactor",
    description="Hide what’s private. Keep what matters."
)

iface.launch(server_name="0.0.0.0", server_port=7860)
