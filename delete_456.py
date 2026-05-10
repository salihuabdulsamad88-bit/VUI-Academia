from app import app, db
from models import Document, Bookmark, RecentView, PdfHighlight, FlashcardDeck
import os

with app.app_context():
    target_ids = [4, 5, 6]
    for doc_id in target_ids:
        doc = Document.query.get(doc_id)
        if doc:
            print(f"Deleting ID {doc_id}: {doc.title}")
            # Related records
            Bookmark.query.filter_by(document_id=doc_id).delete()
            RecentView.query.filter_by(document_id=doc_id).delete()
            PdfHighlight.query.filter_by(document_id=doc_id).delete()
            FlashcardDeck.query.filter_by(document_id=doc_id).update({FlashcardDeck.document_id: None})
            
            # File
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], doc.filename)
            if os.path.exists(file_path):
                os.remove(file_path)
            
            db.session.delete(doc)
        else:
            print(f"ID {doc_id} not found.")
    
    db.session.commit()
    print("Done.")
