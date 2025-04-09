from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class LODWord(db.Model):
    __tablename__ = 'LOD_WORD'
    lodid = db.Column("LODID", db.String, primary_key=True)
    word = db.Column("WORD", db.String, index=True)
    lexcat = db.Column("LEXCAT", db.String, index=True)

    examples = db.relationship("LODExam", backref="word", lazy=True)

class LODExam(db.Model):
    __tablename__ = 'LOD_EXAM'
    id = db.Column("ID", db.Integer, primary_key=True)
    ex_lodid = db.Column("EX_LODID", db.String, db.ForeignKey('LOD_WORD.LODID'))
    example = db.Column("EXAMPLE", db.Text)
    audio = db.Column("AUDIO", db.String)

class LODUserFav(db.Model):
    __tablename__ = 'LOD_USER_FAV'
    id = db.Column("ID", db.Integer, primary_key=True)
    user_id = db.Column("USER_ID", db.String, default="")
    ex_exam_id = db.Column("EX_EXAM_ID", db.Integer, db.ForeignKey('LOD_EXAM.ID'))
    fav_datetime = db.Column("FAV_DATETIME", db.DateTime, default=datetime.utcnow)
