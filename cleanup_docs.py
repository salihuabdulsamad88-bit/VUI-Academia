from app import app, db
from models import Document
import os

with app.app_context():
    docs = Document.query.order_by(Document.id).limit(3).all()
    print(f"Found {len(docs)} documents to delete.")
    for doc in docs:
        print(f"Deleting: {doc.title} ({doc.filename})")
        
        # Delete related records
        from models import Bookmark, RecentView, PdfHighlight, FlashcardDeck
        Bookmark.query.filter_by(document_id=doc.id).delete()
        RecentView.query.filter_by(document_id=doc.id).delete()
        PdfHighlight.query.filter_by(document_id=doc.id).delete()
        # For FlashcardDeck, set document_id to None instead of deleting the deck
        FlashcardDeck.query.filter_by(document_id=doc.id).update({FlashcardDeck.document_id: None})
        
        # Try to delete file
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], doc.filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                print(f"  - File removed: {file_path}")
            except Exception as e:
                print(f"  - Error removing file: {e}")
        else:
            print(f"  - File not found: {file_path}")
        
        # Delete from DB
        db.session.delete(doc)
    
    db.session.commit()
    print("Done.")
