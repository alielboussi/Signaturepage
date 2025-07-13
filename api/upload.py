import base64
import os
import tempfile
from flask import Flask, request, jsonify
from mega import Mega
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# Initialize Firebase
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Login to Mega.nz
mega = Mega()
m = mega.login(email=os.environ.get("MEGA_EMAIL"), password=os.environ.get("MEGA_PASSWORD"))

app = Flask(__name__)

@app.route("/api/upload", methods=["POST"])
def upload():
    try:
        order_id = request.form.get("order_id")
        file = request.files.get("pdf")
        if not order_id or not file:
            return jsonify({"success": False, "message": "Missing order_id or PDF file"}), 400

        # Get order from Firestore using document ID
        doc_ref = db.collection("orders").document(order_id)
        doc_snapshot = doc_ref.get()
        if not doc_snapshot.exists:
            return jsonify({"success": False, "message": "Order not found in Firestore"}), 404

        order_data = doc_snapshot.to_dict()
        driver_name = order_data.get("Driver Name", "Driver")
        branch_name = order_data.get("Branch_Name", order_data.get("branch", "UnknownBranch"))

        # Sanitize filename
        safe_driver = driver_name.replace(" ", "_")
        safe_branch = branch_name.replace(" ", "_")
        date_str = datetime.now().strftime("%d-%m-%Y")
        final_filename = f"{safe_driver}_{safe_branch}_{date_str}.pdf"

        # Save file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            file.save(tmp.name)
            tmp.flush()
            tmp_path = tmp.name

        # Rename temp file for Mega upload
        renamed_path = os.path.join(os.path.dirname(tmp_path), final_filename)
        os.rename(tmp_path, renamed_path)

        # Upload to Mega
        uploaded = m.upload(renamed_path)
        public_url = m.get_upload_link(uploaded)

        # Update Firestore with final info
        doc_ref.update({
            "driver_pdf_url": public_url,
            "driver_pdf_filename": final_filename,
            "driver_pdf_uploaded_at": firestore.SERVER_TIMESTAMP
        })

        return jsonify({"success": True, "pdf_url": public_url, "filename": final_filename})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
