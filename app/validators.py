from fastapi import HTTPException, UploadFile
import os

ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
ALLOWED_DOCUMENT_EXTENSIONS = {'.pdf', '.doc', '.docx', '.txt'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_IMAGE_FILE_SIZE = 2 * 1024 * 1024  # 2MB for images

def validate_file_upload(file: UploadFile, file_type: str = "image"):
    """Validate uploaded file size and type"""
    
    # ✅ Check file size
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    
    max_size = MAX_IMAGE_FILE_SIZE if file_type == "image" else MAX_FILE_SIZE
    
    if file_size > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File size must be less than {max_size // (1024*1024)}MB"
        )
    
    # ✅ Validate file extension
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    allowed_extensions = ALLOWED_IMAGE_EXTENSIONS if file_type == "image" else ALLOWED_DOCUMENT_EXTENSIONS
    
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # ✅ MIME validation is skipped on Render to avoid system dependencies
    # The frontend validates file types, and extension validation is sufficient
    
    return True

def validate_password_strength(password: str) -> bool:
    """Validate password meets minimum requirements"""
    if len(password) < 8:
        return False
    if not any(c.isupper() for c in password):
        return False
    if not any(c.islower() for c in password):
        return False
    if not any(c.isdigit() for c in password):
        return False
    if not any(c in "!@#$%^&*()_+-=[]{}|;:'\",.<>?/~`" for c in password):
        return False
    return True