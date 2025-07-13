import os
import tempfile
import base64
from flask import Flask, request, jsonify
from mega import Mega
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firebase
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Login to Mega.nz
mega = Mega()
m = mega.login(email=os.environ.get("MEGA_EMAIL"), password=os.environ.get("MEGA_PASSWORD"))

app = Flask(__name__)

@app.route("/api/pdf", methods=["POST"])
def generate_and_upload_pdf():
    try:
        data = request.json

        order_id = data.get("order_id")
        driver_name = data.get("driver_name", "Driver")
        branch_name = data.get("branch_name", "UnknownBranch")
        date = data.get("date", datetime.now().strftime("%d-%m-%Y"))
        signature_base64 = data.get("signature_base64")
        item_summary = data.get("item_summary", [])

        if not all([order_id, driver_name, branch_name, signature_base64]):
            return jsonify({"success": False, "message": "Missing required fields"}), 400

        # Decode base64 signature image
        signature_bytes = base64.b64decode(signature_base64.split(',')[-1])
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as sig_img:
            sig_img.write(signature_bytes)
            sig_img_path = sig_img.name

        # Build safe filename
        safe_driver = driver_name.replace(" ", "_")
        safe_branch = branch_name.replace(" ", "_")
        final_filename = f"{safe_driver}_{safe_branch}_{date}.pdf"

        # Generate PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as pdf_file:
            c = canvas.Canvas(pdf_file.name, pagesize=A4)
            width, height = A4

            c.setFont("Helvetica-Bold", 16)
            c.drawString(50, height - 50, "Driver Handover Receipt")

            c.setFont("Helvetica", 12)
            c.drawString(50, height - 80, f"Driver: {driver_name}")
            c.drawString(50, height - 100, f"Branch: {branch_name}")
            c.drawString(50, height - 120, f"Date: {date}")

            c.drawString(50, height - 160, "Items Summary:")
            y = height - 180
            for item in item_summary:
                name = item.get("name", "Item")
                qty = item.get("quantity", "0")
                c.drawString(60, y, f"- {name}: {qty}")
                y -= 20
                if y < 100:
                    c.showPage()
                    y = height - 50

            c.drawString(50, y - 20, "Driver Signature:")
            c.drawImage(sig_img_path, 200, y - 100, width=200, height=80)

            c.save()
            final_pdf_path = pdf_file.name

        # Rename for Mega
        renamed_path = os.path.join(os.path.dirname(final_pdf_path), final_filename)
        os.rename(final_pdf_path, renamed_path)

        # Upload to Mega
        uploaded = m.upload(renamed_path)
        public_url = m.get_upload_link(uploaded)

        # Update Firestore
        doc_ref = db.collection("orders").document(order_id)
        doc_ref.update({
            "driver_pdf_url": public_url,
            "driver_pdf_filename": final_filename,
            "driver_pdf_uploaded_at": firestore.SERVER_TIMESTAMP
        })

        return jsonify({"success": True, "pdf_url": public_url, "filename": final_filename})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
