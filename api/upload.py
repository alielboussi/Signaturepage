import base64
import os
import tempfile
from flask import Response
from mega import Mega
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firebase
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Mega login
mega = Mega()
m = mega.login(email=os.environ.get("MEGA_EMAIL"), password=os.environ.get("MEGA_PASSWORD"))

app = Flask(__name__)

@app.route("/api/upload", methods=["POST"])
def upload():
    try:
        order_id = request.form.get("order_id")
        file = request.files["pdf"]
        if not order_id or not file:
            return jsonify({"success": False, "message": "Missing order_id or pdf file"}), 400

        # Save the PDF temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            file.save(tmp.name)
            tmp.flush()
            tmp_path = tmp.name

        # Upload to Mega
        uploaded = m.upload(tmp_path)
        public_url = m.get_upload_link(uploaded)

        # Update Firestore
        docs = db.collection("orders").where("id", "==", order_id).get()
        if not docs:
            return jsonify({"success": False, "message": "Order not found in Firestore"}), 404
        doc_ref = docs[0].reference
        doc_ref.update({"driver_pdf_url": public_url})

        return jsonify({"success": True, "pdf_url": public_url})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
