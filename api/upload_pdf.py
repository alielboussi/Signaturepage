import os
import tempfile
import json
import uuid
from flask import Flask, request, jsonify
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from supabase import create_client, Client
from datetime import datetime

app = Flask(__name__)

SUPABASE_URL = "https://gysshjhqnooissvqoaus.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imd5c3Noamhxbm9vaXNzdnFvYXVzIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1MjQyMzcxMywiZXhwIjoyMDY3OTk5NzEzfQ.pTdy2yYhs7ChnocvfiML51MxId5y1RF7sVdWGIqBpT4"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def generate_pdf(order_id, driver_name, supervisor_name, branch_name, date_str, time_str, order_cost, item_summary, signature_img_path, role="Driver"):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as pdf_file:
        c = canvas.Canvas(pdf_file.name, pagesize=A4)
        width, height = A4

        y = height - 50
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(width // 2, y, "Driver Handover Receipt")
        y -= 35

        c.setFont("Helvetica", 12)
        c.drawString(50, y, f"Order ID: {order_id}")
        y -= 20
        c.drawString(50, y, f"Date: {date_str}")
        c.drawString(220, y, f"Time: {time_str}")
        y -= 20
        c.drawString(50, y, f"Driver: {driver_name}")
        c.drawString(300, y, f"Role: {role}")
        y -= 20
        c.drawString(50, y, f"Branch: {branch_name}")
        y -= 20
        c.drawString(50, y, f"Supervisor: {supervisor_name}")
        y -= 20
        c.drawString(50, y, f"Approved By: {supervisor_name}")
        y -= 20
        c.drawString(50, y, f"Order Total: K{order_cost}")
        y -= 25

        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "Items Summary:")
        y -= 18
        c.setFont("Helvetica", 12)
        for item in item_summary:
            name = item.get("name", "Item")
            qty = item.get("quantity", "0")
            c.drawString(60, y, f"- {name}: {qty}")
            y -= 16
            if y < 120:
                c.showPage()
                y = height - 50

        y -= 15
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "Driver Signature:")
        y -= 90
        c.drawImage(signature_img_path, 200, y, width=200, height=80)

        c.save()
        return pdf_file.name

@app.route("/api/upload_pdf", methods=["POST"])
def upload_pdf():
    try:
        order_id = request.form.get("order_id") or request.form.get("order_uuid")
        driver_name = request.form.get("driver_name", "Driver")
        supervisor_name = request.form.get("supervisor_name", "Unknown Supervisor")
        branch_name = request.form.get("branch_name", "Unknown Branch")
        order_cost = request.form.get("order_cost", "0.00")
        role = request.form.get("role", "Driver")
        item_summary_raw = request.form.get("item_summary", "[]")

        if not order_id:
            return jsonify({"success": False, "message": "Missing order_id"}), 400

        try:
            item_summary = json.loads(item_summary_raw)
        except Exception:
            item_summary = []

        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        now_iso = now.isoformat()

        signature_file = request.files.get("signature")
        if not signature_file:
            return jsonify({"success": False, "message": "Missing signature file"}), 400

        sig_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        signature_file.save(sig_temp.name)
        sig_temp.close()

        pdf_path = generate_pdf(
            order_id=order_id,
            driver_name=driver_name,
            supervisor_name=supervisor_name,
            branch_name=branch_name,
            date_str=date_str,
            time_str=time_str,
            order_cost=order_cost,
            item_summary=item_summary,
            signature_img_path=sig_temp.name,
            role=role
        )

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

        # 👇 **FINAL FIX: Update status to 'driver signed and order on the way'**
        update_data = {
            "driver_name": driver_name,
            "driver_signature_at": now_iso,
            "driver_pdf_url": public_url,
            "supervisor_name": supervisor_name,
            "status": "driver signed and order on the way"
        }
        update_resp = supabase.table("orders").update(update_data).eq("uuid", order_id).execute()
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
