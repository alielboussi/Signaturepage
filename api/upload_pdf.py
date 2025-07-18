import os
import tempfile
import json
import uuid
from flask import Flask, request, jsonify
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from supabase import create_client, Client
from datetime import datetime

app = Flask(__name__)

SUPABASE_URL = "https://gysshjhqnooissvqoaus.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imd5c3Noamhxbm9vaXNzdnFvYXVzIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1MjQyMzcxMywiZXhwIjoyMDY3OTk5NzEzfQ.pTdy2yYhs7ChnocvfiML51MxId5y1RF7sVdWGIqBpT4"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def calculate_total(items):
    try:
        total = 0.0
        for item in items:
            qty = int(item.get("quantity", 0))
            price = float(item.get("price", 0))
            total += qty * price
        return total
    except Exception:
        return 0.0

def generate_pdf(order_id, supervisor_name, branch_name, date_str, time_str, order_cost, item_summary,
                 driver_name=None, driver_signature_img=None,
                 offloader_name=None, offloader_signature_img=None):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as pdf_file:
        c = canvas.Canvas(pdf_file.name, pagesize=A4)
        width, height = A4

        y = height - 50
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(width // 2, y, "Order Handover Receipt")
        y -= 35

        c.setFont("Helvetica", 12)
        c.drawString(50, y, f"Order ID: {order_id}")
        y -= 20
        c.drawString(50, y, f"Date: {date_str}")
        c.drawString(220, y, f"Time: {time_str}")
        y -= 20
        c.drawString(50, y, f"Branch: {branch_name}")
        y -= 20
        c.drawString(50, y, f"Supervisor: {supervisor_name}")
        y -= 20
        c.drawString(50, y, f"Order Total: K{order_cost:,.2f}")
        y -= 25

        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "Items Summary:")
        y -= 18
        c.setFont("Helvetica", 12)
        if not item_summary:
            c.drawString(60, y, "- (No items)")
            y -= 16
        else:
            for item in item_summary:
                name = item.get("name", "Item")
                qty = item.get("quantity", "0")
                price = item.get("price", "0")
                line = f"- {name}: {qty} × K{price} = K{float(qty)*float(price):,.2f}"
                c.drawString(60, y, line)
                y -= 16
                if y < 120:
                    c.showPage()
                    y = height - 50

        # --- Driver Section ---
        y -= 15
        if driver_name:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(50, y, f"Driver Name: {driver_name}")
            y -= 18
            if driver_signature_img:
                c.setFont("Helvetica-Bold", 12)
                c.drawString(50, y, "Driver Signature:")
                y -= 80
                c.drawImage(driver_signature_img, 200, y, width=200, height=80)
                y -= 15

        # --- Offloader Section ---
        if offloader_name:
            y -= 10
            c.setFont("Helvetica-Bold", 12)
            c.drawString(50, y, f"Offloader Name: {offloader_name}")
            y -= 18
            if offloader_signature_img:
                c.setFont("Helvetica-Bold", 12)
                c.drawString(50, y, "Offloader Signature:")
                y -= 80
                c.drawImage(offloader_signature_img, 200, y, width=200, height=80)
                y -= 15

        c.save()
        return pdf_file.name

@app.route("/api/upload_pdf", methods=["POST"])
def upload_pdf():
    try:
        order_id = request.form.get("order_id") or request.form.get("order_uuid")
        supervisor_name = request.form.get("supervisor_name", "Unknown Supervisor")
        role = (request.form.get("role", "driver") or "driver").lower()

        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        now_iso = now.isoformat()

        # Fetch order data
        order = None
        branch_name = "Unknown Branch"
        item_summary = []
        order_cost = 0.00

        if order_id:
            result = supabase.table("orders").select("*").or_(f"uuid.eq.{order_id},id.eq.{order_id}").limit(1).execute()
            if result.data and len(result.data) > 0:
                order = result.data[0]
                branch_name = order.get("branch", "Unknown Branch")
                try:
                    items_raw = order.get("items", [])
                    if isinstance(items_raw, str):
                        item_summary = json.loads(items_raw)
                    else:
                        item_summary = items_raw
                except Exception:
                    item_summary = []
                order_cost = calculate_total(item_summary)

        # Allow frontend override
        branch_name = request.form.get("branch_name", branch_name)
        item_summary_raw = request.form.get("item_summary")
        order_cost_frontend = request.form.get("order_cost")
        if item_summary_raw:
            try:
                item_summary = json.loads(item_summary_raw)
                order_cost = calculate_total(item_summary)
            except Exception:
                pass
        if order_cost_frontend:
            try:
                order_cost = float(order_cost_frontend)
            except Exception:
                pass

        # --- Signature Files ---
        driver_name = order.get("driver_name", "") if order else ""
        offloader_name = order.get("offloader_name", "") if order else ""
        driver_signature_img = None
        offloader_signature_img = None

        update_data = {
            "supervisor_name": supervisor_name,
        }
        pdf_signer_name = None

        # Handle driver role
        if role == "driver":
            driver_name = request.form.get("driver_name", driver_name)
            signature_file = request.files.get("signature")
            if not signature_file:
                return jsonify({"success": False, "message": "Missing driver signature file"}), 400

            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as sig_temp:
                signature_file.save(sig_temp.name)
                driver_signature_img = sig_temp.name

            update_data.update({
                "driver_name": driver_name,
                "driver_signature_at": now_iso,
            })
            pdf_signer_name = driver_name

        # Handle offloader role
        elif role == "offloader":
            offloader_name = request.form.get("driver_name", offloader_name)  # driver_name reused as offloader_name in frontend
            signature_file = request.files.get("signature")
            if not signature_file:
                return jsonify({"success": False, "message": "Missing offloader signature file"}), 400

            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as sig_temp:
                signature_file.save(sig_temp.name)
                offloader_signature_img = sig_temp.name

            update_data.update({
                "offloader_name": offloader_name,
                "offloader_signature_at": now_iso,
            })
            pdf_signer_name = offloader_name

        else:
            return jsonify({"success": False, "message": "Unsupported role"}), 400

        # Generate PDF with BOTH signatures if available
        pdf_path = generate_pdf(
            order_id=order_id,
            supervisor_name=supervisor_name,
            branch_name=branch_name,
            date_str=date_str,
            time_str=time_str,
            order_cost=order_cost,
            item_summary=item_summary,
            driver_name=driver_name,
            driver_signature_img=driver_signature_img,
            offloader_name=offloader_name,
            offloader_signature_img=offloader_signature_img
        )

        # Clean up sig images
        try:
            if driver_signature_img: os.remove(driver_signature_img)
        except Exception: pass
        try:
            if offloader_signature_img: os.remove(offloader_signature_img)
        except Exception: pass

        safe_signer = (pdf_signer_name or "signer").replace(" ", "_")
        safe_branch = branch_name.replace(" ", "_")
        unique_id = uuid.uuid4().hex[:8]
        filename = f"{safe_signer}_{safe_branch}_{date_str}_{order_id}_{unique_id}.pdf"

        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        response = supabase.storage.from_("driverapproval").upload(filename, pdf_bytes)
        if hasattr(response, "error") and response.error:
            return jsonify({"success": False, "message": "Failed to upload PDF: " + str(response.error)}), 500

        public_url = supabase.storage.from_("driverapproval").get_public_url(filename)
        if not public_url:
            public_url = f"{SUPABASE_URL}/storage/v1/object/public/driverapproval/{filename}"

        # Update DB with correct PDF URL and signature fields
        if role == "driver":
            update_data.update({
                "driver_pdf_url": public_url,
                "status": "driver signed and order on the way"
            })
        elif role == "offloader":
            update_data.update({
                "offloader_pdf_url": public_url,
                "status": "order completed"
            })

        update_resp = supabase.table("orders").update(update_data).or_(f"uuid.eq.{order_id},id.eq.{order_id}").execute()
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
