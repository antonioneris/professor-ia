from fastapi import FastAPI, Request
from dotenv import load_dotenv
import os
import uvicorn
from app.api.whatsapp import router as whatsapp_router
from app.api.assessment import router as assessment_router
from app.api.admin import router as admin_router
from app.database import init_db
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

# Load environment variables
load_dotenv()

app = FastAPI(
    title="Professor AI - English Teacher",
    description="""
    An AI-powered English teacher that interacts with users through WhatsApp.
    
    ## Features
    * English level assessment
    * Personalized study plan generation
    * Daily conversations in text and audio
    * Progress tracking
    * Interactive exercises
    
    ## Authentication
    This API uses token-based authentication for WhatsApp integration.
    Make sure to set up your environment variables properly.
    """,
    version="1.0.0",
    docs_url=None,  # Disable default docs
    redoc_url=None  # Disable default redoc
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers with tags for better organization
app.include_router(
    whatsapp_router,
    prefix="/api/whatsapp",
    tags=["WhatsApp Integration"],
    responses={404: {"description": "Not found"}},
)

app.include_router(
    assessment_router,
    prefix="/api/assessment",
    tags=["Assessment & Study Plans"],
    responses={404: {"description": "Not found"}},
)

app.include_router(
    admin_router,
    prefix="/api/admin",
    tags=["admin"],
    responses={404: {"description": "Not found"}},
)

@app.on_event("startup")
async def startup_event():
    await init_db()

@app.get("/", tags=["Health Check"])
async def root():
    """
    Health check endpoint to verify if the API is running.
    
    Returns:
        dict: A simple message indicating the API is running
    """
    return {"message": "Professor AI - English Teacher API", "status": "running"}

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    """
    Custom Swagger UI with additional styling and configuration.
    """
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - API Documentation",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
        swagger_favicon_url="https://fastapi.tiangolo.com/img/favicon.png"
    )

def custom_openapi():
    """
    Custom OpenAPI schema configuration.
    """
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    
    # Add security schemes
    openapi_schema["components"]["securitySchemes"] = {
        "WhatsAppToken": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "WhatsApp Business API Token"
        }
    }
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 