from app import app, db
from models import Document

with app.app_context():
    docs = Document.query.order_by(Document.id).all()
    print(f"Total documents: {len(docs)}")
    for doc in docs:
        print(f"ID: {doc.id} | Title: {doc.title} | Filename: {doc.filename}")
