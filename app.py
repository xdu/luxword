import csv
import requests
import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from models import db, LODWord, LODExam, LODUserFav
from sqlalchemy import func
from flask_migrate import Migrate

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# SQLite DB config
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///lod_words.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

migrate = Migrate()
migrate.init_app(app, db)

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

    # Filter by selected LEXCAT(s) if any
    if selected_lexcats:
        words = (
            LODWord.query
            .filter(LODWord.lexcat.in_(selected_lexcats))
            .order_by(LODWord.word)
            .all()
        )
    else:
        words = LODWord.query.order_by(LODWord.word).all()

    return render_template("index.html", words=words, categories=categories, selected_lexcats=selected_lexcats)

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
    record = db.session.get(LODUserFav, fav_id)
    if record:
        db.session.delete(record)
        db.session.commit()
        return jsonify({"status": "ok"})
    return jsonify({"status": "not found"}), 404

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

if __name__ == '__main__':
    app.run(debug=True)
