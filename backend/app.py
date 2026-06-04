from flask import Flask, request, render_template, send_file, jsonify
import PyPDF2
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.text_rank import TextRankSummarizer
from flask import Flask, request, render_template, send_file, jsonify, session
from gtts import gTTS
from deep_translator import GoogleTranslator
import nltk
import os
from pdf2image import convert_from_bytes
from PIL import Image
import pytesseract
import re
from nltk.corpus import wordnet as wn
from nltk.tokenize import word_tokenize, sent_tokenize
import random
from flask import session

# NLTK setup
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')

app = Flask(__name__)
app.secret_key = "a8d9f0g1h2j3k4l5m6n7p8q9r0s1t2u3"

app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB

from werkzeug.exceptions import RequestEntityTooLarge

@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    return "File is too large. Maximum allowed size is 50 MB.", 413

STATIC_DIR = "static"
FULL_AUDIO = os.path.join(STATIC_DIR, "full_audio.mp3")
RANGE_AUDIO = os.path.join(STATIC_DIR, "range_audio.mp3")
PRONOUNCE_AUDIO = os.path.join(STATIC_DIR, "pronounce.mp3")

os.makedirs(STATIC_DIR, exist_ok=True)

# ---------------- OCR normalization ----------------
def normalize_ocr_for_tts(text):
    text = re.sub(r'-\s+', '', text)
    text = re.sub(r'\n+', '. ', text)
    text = re.sub(r'\s+', ' ', text)
    if not text.endswith('.'):
        text += '.'
    return text.strip()

@app.route('/')
def home():
    return render_template("index.html")  # or your upload page name

# ---------------- Routes ----------------
@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['file']
    full_text = ""
    lines = []
    pages_text = []  # <-- ADD THIS

    if file.filename.endswith('.pdf'):
        reader = PyPDF2.PdfReader(file)
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                full_text += text + "\n"
                page_lines = text.splitlines()
                lines.extend(page_lines)

                # Store each page text separately
                pages_text.append(text)  # <-- ADD THIS

                # Add page-end marker
                lines.append(f"--- End of Page {i+1} ---")
                full_text += f"\n--- End of Page {i+1} ---\n"

    # Store in session
    session['pages_text'] = pages_text

    # Summarize whole text
    parser = PlaintextParser.from_string(full_text, Tokenizer("english"))
    summarizer = TextRankSummarizer()
    num_sentences = max(3, min(20, len(parser.document.sentences)//3))
    summary = " ".join(str(s) for s in summarizer(parser.document, num_sentences))

    return render_template(
        "result.html",
        text=full_text,
        lines=lines,
        summary=summary,
        pages_text=pages_text  # <-- pass to template
    )

# ---------------- Translation / Audio ----------------
@app.route('/play-range', methods=['POST'])
def play_range():
    target_lang = request.form.get('range_language', 'en')
    selected_text = request.form.get('lines_text', '')

    if not selected_text:
        return ("No text selected", 400)

    rebuilt_text = rebuild_sentences(selected_text)
    translated_text = GoogleTranslator(source='auto', target=target_lang).translate(rebuilt_text)
    gTTS(translated_text, lang=target_lang, slow=False).save(RANGE_AUDIO)
    return ("", 204)

@app.route('/play-full-audio', methods=['POST'])
def play_full_audio():
    target_lang = request.form.get('full_language', 'en')
    page_number = request.form.get('page_number')

    pages_text = session.get('pages_text', [])

    if page_number:
        page_number = int(page_number)
        if page_number < 1 or page_number > len(pages_text):
            return ("Invalid page", 400)
        text = pages_text[page_number - 1]
    else:
        text = " ".join(pages_text)

    translated_text = GoogleTranslator(source='auto', target=target_lang).translate(text)
    gTTS(translated_text, lang=target_lang).save(FULL_AUDIO)

    return send_file(FULL_AUDIO, mimetype="audio/mpeg")


@app.route('/translate-text', methods=['POST'])
def translate_text():
    target_lang = request.form.get('language', 'en')
    page_number = request.form.get('page_number')

    if not page_number:
        return {"translated_text": "No page number provided"}

    try:
        page_number = int(page_number)
        pages_text = session.get('pages_text', [])
        if not pages_text or page_number < 1 or page_number > len(pages_text):
            return {"translated_text": "Invalid page number"}
        text_to_translate = pages_text[page_number - 1]
    except Exception as e:
        return {"translated_text": f"Error: {str(e)}"}

    translated = GoogleTranslator(source='auto', target=target_lang).translate(text_to_translate)
    return {"translated_text": translated}

@app.route('/page-summary', methods=['POST'])
def page_summary():
    page_number = request.form.get('page_number')

    if not page_number:
        return jsonify({"summary": "No page number provided"})

    try:
        page_number = int(page_number)
        pages_text = session.get('pages_text', [])

        if not pages_text or page_number < 1 or page_number > len(pages_text):
            return jsonify({"summary": "Invalid page number"})

        text = pages_text[page_number - 1]

        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        summarizer = TextRankSummarizer()

        num_sentences = max(2, min(10, len(parser.document.sentences)//2))
        summary = " ".join(str(s) for s in summarizer(parser.document, num_sentences))

        return jsonify({"summary": summary})

    except Exception as e:
        return jsonify({"summary": f"Error: {str(e)}"})

# ---------------- Vocabulary Helper ----------------
@app.route('/vocabulary', methods=['POST'])
def vocabulary():
    word = request.form.get('word', '').strip()
    if not word:
        return jsonify({"meaning": "No word provided", "example": "", "synonyms": [], "antonyms": []})

    try:
        synsets = wn.synsets(word)
        if not synsets:
            return jsonify({"meaning": "Meaning not found", "example": "No example available", "synonyms": [], "antonyms": []})

        meaning = synsets[0].definition()
        examples = synsets[0].examples()
        example = examples[0] if examples else "No example available"

        synonyms = {lemma.name() for syn in synsets for lemma in syn.lemmas() if lemma.name() != word}
        antonyms = {ant.name() for syn in synsets for lemma in syn.lemmas() for ant in lemma.antonyms()}

        return jsonify({
            "meaning": meaning,
            "example": example,
            "synonyms": list(synonyms)[:5],
            "antonyms": list(antonyms)[:5]
        })

    except Exception as e:
        return jsonify({"meaning": f"Error: {str(e)}", "example": "", "synonyms": [], "antonyms": []})
    
    
# ---------------- Pronunciation ----------------
@app.route('/pronounce-word', methods=['POST'])
def pronounce_word():
    word = request.form.get('word', '').strip()
    if not word:
        return "No word provided", 400
    tts = gTTS(word, lang='en')
    tts.save(PRONOUNCE_AUDIO)
    return send_file(PRONOUNCE_AUDIO, mimetype="audio/mpeg")

# ---------------- Helpers ----------------
def rebuild_sentences(text):
    text = text.replace('\n', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    sentences = sent_tokenize(text)
    return " ".join(sentences)

@app.route('/generate-mcq', methods=['POST'])
def generate_mcq():
    text = request.form.get('text', '')
    questions = []

    if not text:
        return jsonify({"questions": []})

    sentences = sent_tokenize(text)

    for sent in sentences:
        words = [w for w in word_tokenize(sent) if w.isalpha() and len(w) > 3]
        if len(words) < 4:   # ensure enough words
            continue

        keyword = random.choice(words)
        question_text = sent.replace(keyword, "_____")

        distractors = []
        synsets = wn.synsets(keyword.lower())

        # Try synonym-based distractors
        if synsets:
            for lemma in synsets[0].lemmas():
                w = lemma.name().replace("_", " ")
                if w.isalpha() and w.lower() != keyword.lower():
                    distractors.append(w.capitalize())

        # Remove duplicates early
        distractors = list(set([d.lower() for d in distractors]))
        distractors = [d.capitalize() for d in distractors]

        # If not enough, fill from sentence words
        while len(distractors) < 3:
            filler = random.choice(words).capitalize()
            if filler.lower() != keyword.lower() and filler not in distractors:
                distractors.append(filler)

        # Final options
        options = distractors[:3] + [keyword.capitalize()]

        # Remove duplicates again safely
        options = list(dict.fromkeys([opt.capitalize() for opt in options]))

        # Ensure exactly 4 options
        while len(options) < 4:
            filler = random.choice(words).capitalize()
            if filler not in options:
                options.append(filler)

        random.shuffle(options)

        questions.append({
            "question": question_text,
            "options": options,
            "answer": keyword.capitalize()
        })

    return jsonify({"questions": questions})

if __name__ == "__main__":
    app.run(debug=True)