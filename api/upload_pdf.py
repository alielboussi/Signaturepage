import os
import tempfile
import json
import uuid
from flask import Flask, request, jsonify
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from PIL import Image
from io import BytesIO
from supabase import create_client, Client
from datetime import datetime

app = Flask(__name__)

SUPABASE_URL = "https://gysshjhqnooissvqoaus.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imd5c3Noamhxbm9vaXNzdnFvYXVzIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1MjQyMzcxMywiZXhwIjoyMDY3OTk5NzEzfQ.pTdy2yYhs7ChnocvfiML51MxId5y1RF7sVdWGIqBpT4"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def generate_pdf(driver_name, branch_name, date_str, item_summary, signature_img_path):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as pdf_file:
        c = canvas.Canvas(pdf_file.name, pagesize=A4)
        width, height = A4

        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, height - 50, "Driver Handover Receipt")

        c.setFont("Helvetica", 12)
        c.drawString(50, height - 80, f"Driver: {driver_name}")
        c.drawString(50, height - 100, f"Branch: {branch_name}")
        c.drawString(50, height - 120, f"Date: {date_str}")

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
        c.drawImage(signature_img_path, 200, y - 100, width=200, height=80)

        c.save()
        return pdf_file.name

@app.route("/api/upload-pdf", methods=["POST"])
def upload_pdf():
    try:
        order_id = request.form.get("order_id")
        driver_name = request.form.get("driver_name", "Driver")
        branch_name = request.form.get("branch_name", "UnknownBranch")
        item_summary_raw = request.form.get("item_summary", "[]")

        if not order_id:
            return jsonify({"success": False, "message": "Missing order_id"}), 400

        try:
            item_summary = json.loads(item_summary_raw)
        except Exception:
            item_summary = []

        date_str = datetime.now().strftime("%Y-%m-%d")

        signature_file = request.files.get("signature")
        if not signature_file:
            return jsonify({"success": False, "message": "Missing signature file"}), 400

        sig_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        signature_file.save(sig_temp.name)
        sig_temp.close()

        pdf_path = generate_pdf(driver_name, branch_name, date_str, item_summary, sig_temp.name)

        try:
            os.remove(sig_temp.name)
        except Exception:
            pass

        safe_driver = driver_name.replace(" ", "_")
        safe_branch = branch_name.replace(" ", "_")
        unique_id = uuid.uuid4().hex[:8]
        filename = f"{safe_driver}_{safe_branch}_{date_str}_{order_id}_{unique_id}.pdf"

        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        response = supabase.storage.from_("driverapproval").upload(filename, pdf_bytes)

        if hasattr(response, "error") and response.error:
            return jsonify({"success": False, "message": "Failed to upload PDF: " + str(response.error)}), 500

        public_url = supabase.storage.from_("driverapproval").get_public_url(filename)

        if not public_url:
            public_url = f"{SUPABASE_URL}/storage/v1/object/public/driverapproval/{filename}"

        update_resp = supabase.table("orders").update({"driver_pdf_url": public_url}).eq("id", order_id).execute()

        if hasattr(update_resp, "error") and update_resp.error:
            return jsonify({"success": False, "message": "Failed to update orders table: " + str(update_resp.error)}), 500

        try:
            os.remove(pdf_path)
        except Exception:
            pass

        return jsonify({"success": True, "pdf_url": public_url, "filename": filename})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
