from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client
from datetime import datetime, timedelta
import os
import uuid
import json
from functools import wraps

app = Flask(__name__)
CORS(app, origins=["*"])

# Supabase setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============ HELPER FUNCTIONS ============

def get_guest_id():
    """Extract guest ID from request headers"""
    return request.headers.get("X-Guest-ID")

def require_guest_id(f):
    """Decorator to require guest ID"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        guest_id = get_guest_id()
        if not guest_id:
            return jsonify({"error": "Guest ID required"}), 401
        return f(guest_id, *args, **kwargs)
    return decorated_function

def set_guest_context(guest_id: str):
    """Set Supabase session context for RLS"""
    try:
        supabase.postgrest.auth(guest_id)
    except:
        pass

# ============ AUTH ROUTES ============

@app.route("/api/auth/guest", methods=["POST"])
def create_guest():
    """Create a new guest session"""
    try:
        guest_id = str(uuid.uuid4())
        
        # Create user in Supabase
        response = supabase.table("users").insert({
            "guest_id": guest_id,
            "created_at": datetime.utcnow().isoformat(),
            "last_accessed": datetime.utcnow().isoformat()
        }).execute()
        
        return jsonify({
            "guest_id": guest_id,
            "user_id": response.data[0]["id"] if response.data else None
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/auth/verify", methods=["POST"])
@require_guest_id
def verify_guest(guest_id: str):
    """Verify guest session and get user info"""
    try:
        response = supabase.table("users").select("*").eq("guest_id", guest_id).execute()
        
        if not response.data:
            return jsonify({"error": "Guest not found"}), 404
        
        user = response.data[0]
        
        # Update last accessed
        supabase.table("users").update({
            "last_accessed": datetime.utcnow().isoformat()
        }).eq("id", user["id"]).execute()
        
        return jsonify({
            "user_id": user["id"],
            "guest_id": user["guest_id"],
            "created_at": user["created_at"]
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============ IMAGE ROUTES ============

@app.route("/api/images", methods=["GET"])
@require_guest_id
def get_images(guest_id: str):
    """Get all images for the current user"""
    try:
        user = supabase.table("users").select("id").eq("guest_id", guest_id).execute()
        if not user.data:
            return jsonify({"error": "User not found"}), 404
        
        user_id = user.data[0]["id"]
        
        images = supabase.table("images").select("*").eq("user_id", user_id).order("display_order").execute()
        
        return jsonify(images.data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/images", methods=["POST"])
@require_guest_id
def create_image(guest_id: str):
    """Create a new image"""
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get("image_url"):
            return jsonify({"error": "image_url is required"}), 400
        
        # Get user ID
        user = supabase.table("users").select("id").eq("guest_id", guest_id).execute()
        if not user.data:
            return jsonify({"error": "User not found"}), 404
        
        user_id = user.data[0]["id"]
        
        # Get max order
        images = supabase.table("images").select("display_order").eq("user_id", user_id).order("display_order", desc=True).limit(1).execute()
        next_order = (images.data[0]["display_order"] if images.data else -1) + 1
        
        # Create image
        response = supabase.table("images").insert({
            "user_id": user_id,
            "title": data.get("title", "Untitled"),
            "image_url": data.get("image_url"),
            "description": data.get("description", ""),
            "display_order": next_order,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }).execute()
        
        return jsonify(response.data[0]), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/images/<image_id>", methods=["PUT"])
@require_guest_id
def update_image(guest_id: str, image_id: str):
    """Update an image"""
    try:
        data = request.get_json()
        
        # Verify ownership
        user = supabase.table("users").select("id").eq("guest_id", guest_id).execute()
        if not user.data:
            return jsonify({"error": "User not found"}), 404
        
        user_id = user.data[0]["id"]
        image = supabase.table("images").select("*").eq("id", image_id).eq("user_id", user_id).execute()
        
        if not image.data:
            return jsonify({"error": "Image not found or access denied"}), 404
        
        # Update
        update_data = {
            "updated_at": datetime.utcnow().isoformat()
        }
        if "title" in data:
            update_data["title"] = data["title"]
        if "description" in data:
            update_data["description"] = data["description"]
        if "image_url" in data:
            update_data["image_url"] = data["image_url"]
        if "display_order" in data:
            update_data["display_order"] = data["display_order"]
        
        response = supabase.table("images").update(update_data).eq("id", image_id).execute()
        
        return jsonify(response.data[0]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/images/<image_id>", methods=["DELETE"])
@require_guest_id
def delete_image(guest_id: str, image_id: str):
    """Delete an image"""
    try:
        # Verify ownership
        user = supabase.table("users").select("id").eq("guest_id", guest_id).execute()
        if not user.data:
            return jsonify({"error": "User not found"}), 404
        
        user_id = user.data[0]["id"]
        image = supabase.table("images").select("*").eq("id", image_id).eq("user_id", user_id).execute()
        
        if not image.data:
            return jsonify({"error": "Image not found or access denied"}), 404
        
        # Delete
        supabase.table("images").delete().eq("id", image_id).execute()
        
        return jsonify({"message": "Image deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/images/reorder", methods=["POST"])
@require_guest_id
def reorder_images(guest_id: str):
    """Reorder images"""
    try:
        data = request.get_json()
        order_list = data.get("order", [])  # List of {id, order}
        
        user = supabase.table("users").select("id").eq("guest_id", guest_id).execute()
        if not user.data:
            return jsonify({"error": "User not found"}), 404
        
        user_id = user.data[0]["id"]
        
        # Update all images
        for item in order_list:
            supabase.table("images").update({
                "display_order": item["order"]
            }).eq("id", item["id"]).eq("user_id", user_id).execute()
        
        return jsonify({"message": "Reordered"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/upload", methods=["POST"])
@require_guest_id
def upload_file(guest_id: str):
    """Handle file upload - return URL only (client handles storing URL)"""
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400
        
        # Get user ID
        user = supabase.table("users").select("id").eq("guest_id", guest_id).execute()
        if not user.data:
            return jsonify({"error": "User not found"}), 404
        
        user_id = user.data[0]["id"]
        
        # Generate unique filename
        file_ext = os.path.splitext(file.filename)[1]
        unique_filename = f"{user_id}/{uuid.uuid4()}{file_ext}"
        
        # Upload to Supabase Storage
        file_data = file.read()
        response = supabase.storage.from_("images").upload(
            unique_filename,
            file_data,
            {"content-type": file.content_type}
        )
        
        # Get public URL
        public_url = supabase.storage.from_("images").get_public_url(unique_filename)
        
        return jsonify({
            "url": public_url,
            "filename": unique_filename
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(debug=True, port=5000)
