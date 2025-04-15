import csv
import requests
import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from models import db, LODWord, LODExam, LODUserFav, SDL_CARD 
from sqlalchemy import func
from sqlalchemy.orm import outerjoin # Added import
from flask_migrate import Migrate
from googletrans import Translator

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# SQLite DB config
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///lod_words.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

migrate = Migrate()
migrate.init_app(app, db)

translator = Translator()

# CLI command to create tables
@app.cli.command("init-db")
def init_db():
    db.create_all()
    print("Initialized the database.")

@app.route('/')
def index():
    selected_lexcats = request.args.getlist('lexcat')

    # Group by LEXCAT with word counts
    categories = (
        db.session.query(LODWord.lexcat, func.count(LODWord.word))
        .group_by(LODWord.lexcat)
        .order_by(LODWord.lexcat)
            .all()
        )

    # Base query joining LODWord with LODExam to check for examples
    query = db.session.query(
        LODWord,
        (LODExam.id != None).label('has_examples') # Create a boolean label
    ).outerjoin(LODExam, LODWord.lodid == LODExam.ex_lodid) \
     .group_by(LODWord.lodid) # Group by word to count examples per word

    # Filter by selected LEXCAT(s) if any
    if selected_lexcats:
        query = query.filter(LODWord.lexcat.in_(selected_lexcats))

    # Order and execute
    word_data = query.order_by(LODWord.word).all()

    # Pass the combined data to the template
    return render_template("index.html", word_data=word_data, categories=categories, selected_lexcats=selected_lexcats)

@app.route('/toggle_fav', methods=['POST'])
def toggle_fav():
    exam_id = request.json.get('exam_id')
    user_id = request.json.get('user_id', '')

    fav = LODUserFav.query.filter_by(user_id=user_id, ex_exam_id=exam_id).first()

    if fav:
        db.session.delete(fav)
        db.session.commit()
        return jsonify({'status': 'removed'})
    else:
        new_fav = LODUserFav(
            user_id=user_id,
            ex_exam_id=exam_id,
            fav_datetime=datetime.datetime.now(datetime.timezone.utc)  # Explicitly set the datetime
        )
        db.session.add(new_fav)
        db.session.commit()
        return jsonify({'status': 'added'})

@app.route('/get_examples/<lodid>')
def get_examples(lodid):
    user_id = ""  # Default anon user

    # Check local DB first
    examples = (
        db.session.query(LODExam, LODUserFav.id)
        .outerjoin(LODUserFav, (LODUserFav.ex_exam_id == LODExam.id) & (LODUserFav.user_id == user_id))
        .filter(LODExam.ex_lodid == lodid)
        .all()
    )

    # If not found, fetch from web API
    if not examples:
        try:
            response = requests.get(f"https://lod.lu/api/lb/entry/{lodid}")
            if response.ok:
                data = response.json()
                example_objs = extract_examples_from_json(data)

                for ex in example_objs:
                    new_ex = LODExam(
                        ex_lodid=lodid,
                        example=ex['text'],
                        audio=ex['audio']
                    )
                    db.session.add(new_ex)
                db.session.commit()

                # Fetch again after inserting
                examples = (
                    db.session.query(LODExam, LODUserFav.id)
                    .outerjoin(LODUserFav, (LODUserFav.ex_exam_id == LODExam.id) & (LODUserFav.user_id == user_id))
                    .filter(LODExam.ex_lodid == lodid)
                    .all()
                )

        except Exception as e:
            print(f"Failed to fetch examples for {lodid}: {e}")

    return jsonify({
        'examples': [
            {
                'id': ex.LODExam.id,
                'text': ex.LODExam.example,
                'audio': ex.LODExam.audio,
                'is_fav': ex.id is not None
            } for ex in examples
        ]
    })

def extract_examples_from_json(data):
    examples_list = []

    def recursive_search(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "examples" and isinstance(value, list):
                    for example in value:
                        audio = example.get("audioFiles", {}).get("aac")
                        if not audio:
                            continue

                        # Extract the sentence text
                        parts_list = example.get("parts", [])
                        text_sentence = None
                        for part in parts_list:
                            if part.get("type") == "text":
                                text_parts = part.get("parts", [])
                                words = []
                                for tp in text_parts:
                                    content = tp.get("content", "")
                                    join = tp.get("joinWithPreviousWord", False)
                                    if join and words:
                                        words[-1] += content
                                    else:
                                        words.append(content)
                                text_sentence = " ".join(words)
                                break

                        if text_sentence and audio:
                            examples_list.append({
                                "text": text_sentence,
                                "audio": audio
                            })
                else:
                    recursive_search(value)
        elif isinstance(obj, list):
            for item in obj:
                recursive_search(item)

    recursive_search(data)
    return examples_list

@app.route("/favorites")
def favorites():
    user_id = ""  # replace with actual logged-in user ID if available

    favorites = (
        db.session.query(LODUserFav, LODExam)
        .join(LODExam, LODUserFav.ex_exam_id == LODExam.id)
        .filter(LODUserFav.user_id == user_id)
        .order_by(LODUserFav.fav_datetime.desc())
        .all()
    )

    from collections import defaultdict
    from datetime import datetime

    grouped = defaultdict(list)
    for fav, exam in favorites:
        date_key = fav.fav_datetime.strftime("%Y-%m-%d")
        grouped[date_key].append({
            "fav_id": fav.id,
            "exam_id": exam.id,
            "example": exam.example,
            "audio": exam.audio
        })

    return render_template("favorites.html", grouped=grouped)

@app.route("/unfavorite/<int:fav_id>", methods=["POST"])
def unfavorite_example(fav_id):
    fav = db.session.get(LODUserFav, fav_id)
    if not fav:
        return jsonify({"status": "not found"}), 404

    exam = db.session.get(LODExam, fav.ex_exam_id)
    db.session.delete(fav)

    # Delete orphan manual example
    if exam and exam.EX_LODID is None:
        db.session.delete(exam)

    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/add_manual_favorite", methods=["POST"])
def add_manual_favorite():
    user_id = ""  # Replace with session-based user if needed
    sentence = request.form.get("example", "").strip()

    if not sentence:
        return jsonify({"status": "empty"}), 400

    # Insert into LOD_EXAM without a LODID or AUDIO
    new_exam = LODExam(ex_lodid=None, example=sentence, audio=None)
    db.session.add(new_exam)
    db.session.commit()

    # Then add to favorites
    new_fav = LODUserFav(user_id=user_id, ex_exam_id=new_exam.id)
    db.session.add(new_fav)
    db.session.commit()

    return jsonify({"status": "ok"})

@app.route("/add_word", methods=["GET", "POST"])
def add_word():
    if request.method == "POST":
        query = request.form.get("search", "").strip()
        if not query:
            return render_template("add_word.html", results=[], query="")

        try:
            res = requests.get(f"https://lod.lu/api/lb/search?query={query}&lang=lb")
            if res.ok:
                data = res.json()
                results = data.get("results", [])
                return render_template("add_word.html", results=results, query=query)
        except Exception as e:
            print(f"Search error: {e}")

        return render_template("add_word.html", results=[], query=query)

    return render_template("add_word.html", results=[], query="")

@app.route("/add_word_to_db", methods=["POST"])
def add_word_to_db():
    lodid = request.json.get("lodid")
    word = request.json.get("word")
    pos = request.json.get("pos", None)

    if not lodid or not word:
        return jsonify({"status": "error", "message": "Missing data"}), 400

    # Corrected model name from LOD_WORDS to LODWord
    existing = db.session.get(LODWord, lodid)
    if existing:
        return jsonify({"status": "exists"})

    # Corrected model name and attribute names (lowercase)
    new_word = LODWord(lodid=lodid, word=word, lexcat=pos)
    db.session.add(new_word)
    db.session.commit()
    return jsonify({"status": "added"})

@app.route("/flashcards")
def flashcards():
    cards = SDL_CARD.query.order_by(SDL_CARD.ID.desc()).all()
    return render_template("flashcards.html", cards=cards)

@app.route("/flashcards/create", methods=["GET", "POST"])
def create_flashcard():
    if request.method == "POST":
        audio_url = request.form.get("audio_url", "").strip()
        transcript = request.form.get("transcript", "").strip()
        translation = request.form.get("translation", "").strip()

        if not audio_url or not transcript or not translation:
            flash("All fields are required.", "is-danger")
            return redirect(url_for("create_flashcard"))

        existing = SDL_CARD.query.filter_by(AUDIO_URL=audio_url).first()
        if existing:
            flash("Audio URL already exists in database.", "is-warning")
            return redirect(url_for("create_flashcard"))

        card = SDL_CARD(AUDIO_URL=audio_url, TRANSCRIPT=transcript, TRANSLATION=translation)
        db.session.add(card)
        db.session.commit()
        return redirect(url_for("flashcards"))

    return render_template("create_flashcard.html")

@app.route("/flashcards/<int:card_id>")
def view_flashcard(card_id):
    card = db.session.get(SDL_CARD, card_id)
    if not card:
        flash("Card not found", "is-danger")
        return redirect(url_for("flashcards"))
    return render_template("flashcard_detail.html", card=card)

# Update a flashcard
@app.route("/flashcards/<int:card_id>/update", methods=["POST"])
def update_flashcard(card_id):
    card = db.session.get(SDL_CARD, card_id)
    if not card:
        return jsonify({"status": "error", "message": "Card not found"}), 404
    
    card.AUDIO_URL = request.form.get("audio_url", card.AUDIO_URL)
    card.TRANSCRIPT = request.form.get("transcript", card.TRANSCRIPT)
    card.TRANSLATION = request.form.get("translation", card.TRANSLATION)
    
    db.session.commit()
    return jsonify({"status": "success"})

# Delete a flashcard
@app.route("/flashcards/<int:card_id>/delete", methods=["POST"])
def delete_flashcard(card_id):
    card = db.session.get(SDL_CARD, card_id)
    if not card:
        return jsonify({"status": "error", "message": "Card not found"}), 404
    
    db.session.delete(card)
    db.session.commit()
    return jsonify({"status": "success"})

@app.route("/flashcards/translate", methods=["POST"])
def translate_transcript():
    data = request.json
    transcript = data.get("transcript", "")
    if not transcript:
        return jsonify({"translation": ""})

    result = translator.translate(transcript, dest="zh-CN")
    return jsonify({"translation": result.text})

@app.route('/import')
def importfile():
    return render_template('import.html')

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['file']
    if not file or not file.filename.endswith('.csv'):
        flash("Please upload a valid CSV file.")
        return redirect(url_for('index'))

    csv_data = file.stream.read().decode("utf-8").splitlines()
    reader = csv.reader(csv_data, delimiter=';')
    imported = 0
    for row in reader:
        if len(row) >= 2:
            lodid = row[0].strip()
            word = row[1].strip()
            lexcat = row[2].strip() if len(row) > 2 and row[2].strip() else None
            if not db.session.get(LODWord, lodid):
                db.session.add(LODWord(lodid=lodid, word=word, lexcat=lexcat))
                imported += 1
    db.session.commit()

    flash(f"Successfully imported {imported} words.")
    return redirect(url_for('index'))

@app.template_filter('nl2br')
def nl2br(value):
    return value.replace('\n', '<br>')

if __name__ == '__main__':
    app.run(debug=True)
