from app import app, db
from models import Document, Bookmark, RecentView, PdfHighlight, FlashcardDeck
import os

titles_to_delete = [
    "BIOCHEMISTRY",
    "Acids Bases And Salts",
    "5 - Proteins And Amino Acids Revised 9-24-2018",
    "CHM 101"
]

with app.app_context():
    for title in titles_to_delete:
        docs = Document.query.filter(Document.title.ilike(f"%{title}%")).all()
        for doc in docs:
            print(f"Deleting {doc.id}: {doc.title}")
            
            # Related records
            Bookmark.query.filter_by(document_id=doc.id).delete()
            RecentView.query.filter_by(document_id=doc.id).delete()
            PdfHighlight.query.filter_by(document_id=doc.id).delete()
            FlashcardDeck.query.filter_by(document_id=doc.id).update({FlashcardDeck.document_id: None})
            
            # File
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], doc.filename)
            if os.path.exists(file_path):
                os.remove(file_path)
            
            db.session.delete(doc)
    
    db.session.commit()
    print("Done.")
