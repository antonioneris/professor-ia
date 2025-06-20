import requests
import os
from typing import Dict, Any, Optional
import json
import logging

logger = logging.getLogger(__name__)

class WhatsAppService:
    def __init__(self):
        self.token = os.getenv("WHATSAPP_TOKEN")
        self.phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        self.api_version = os.getenv("WHATSAPP_API_VERSION", "v17.0")
        self.base_url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}"
        
        logger.info(f"Initialized WhatsAppService with phone_number_id: {self.phone_number_id}, api_version: {self.api_version}")
        if not self.token or not self.phone_number_id:
            logger.error("WhatsApp credentials not properly configured")
            raise Exception("WhatsApp credentials not configured")

    def send_message(self, to: str, text: str) -> dict:
        """Send a text message via WhatsApp."""
        try:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
            
            data = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"body": text}
            }
            
            response = requests.post(
                f"{self.base_url}/messages",
                headers=headers,
                json=data
            )
            
            if response.status_code == 400:
                error_data = response.json().get('error', {})
                error_code = error_data.get('code')
                
                if error_code == 131030:
                    logger.warning(f"Phone number {to} not in allowed list. This is expected during development.")
                    error_details = error_data.get('error_data', {}).get('details', '')
                    raise WhatsAppPermissionError(f"Phone number not allowed: {error_details}")
                else:
                    logger.error(f"WhatsApp API error: {response.status_code} - {response.json()}")
                    raise WhatsAppAPIError(f"WhatsApp API error: {response.json()}")
            
            response.raise_for_status()
            return response.json()
            
        except WhatsAppPermissionError as e:
            # Re-raise permission errors to handle them differently
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending WhatsApp message: {str(e)}")
            raise WhatsAppAPIError(f"Failed to send message: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in send_message: {str(e)}")
            raise WhatsAppAPIError(f"Unexpected error: {str(e)}")

    def send_audio(self, to: str, audio_url: str) -> dict:
        """Send an audio message via WhatsApp."""
        try:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
            
            data = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "audio",
                "audio": {"link": audio_url}
            }
            
            response = requests.post(
                f"{self.base_url}/messages",
                headers=headers,
                json=data
            )
            
            if response.status_code == 400:
                error_data = response.json().get('error', {})
                error_code = error_data.get('code')
                
                if error_code == 131030:
                    logger.warning(f"Phone number {to} not in allowed list. This is expected during development.")
                    error_details = error_data.get('error_data', {}).get('details', '')
                    raise WhatsAppPermissionError(f"Phone number not allowed: {error_details}")
                else:
                    logger.error(f"WhatsApp API error: {response.status_code} - {response.json()}")
                    raise WhatsAppAPIError(f"WhatsApp API error: {response.json()}")
            
            response.raise_for_status()
            return response.json()
            
        except WhatsAppPermissionError as e:
            # Re-raise permission errors to handle them differently
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending WhatsApp audio: {str(e)}")
            raise WhatsAppAPIError(f"Failed to send audio: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in send_audio: {str(e)}")
            raise WhatsAppAPIError(f"Unexpected error: {str(e)}")

    def verify_webhook(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """Verify webhook endpoint for WhatsApp API setup."""
        verify_token = os.getenv('WHATSAPP_VERIFY_TOKEN')
        
        if not verify_token:
            logger.error("Webhook verify token not configured")
            return None
            
        if mode == "subscribe" and token == verify_token:
            return challenge
            
        return None

    def send_template_message(self, to: str, template_name: str, language_code: str = "en_US") -> Dict[str, Any]:
        """Send a template message to a WhatsApp user."""
        endpoint = f"{self.base_url}/messages"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": language_code
                }
            }
        }

        try:
            logger.info(f"Sending WhatsApp template message to {to}: {template_name}")
            logger.debug(f"Request to {endpoint} with data: {json.dumps(data, indent=2)}")
            
            response = requests.post(endpoint, headers=headers, json=data)
            response_json = response.json()
            
            logger.info(f"WhatsApp API response: {json.dumps(response_json, indent=2)}")
            
            if response.status_code != 200:
                logger.error(f"WhatsApp API error: {response.status_code} - {response_json}")
            
            response.raise_for_status()
            return response_json
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending WhatsApp template message: {str(e)}", exc_info=True)
            raise 

class WhatsAppAPIError(Exception):
    """Generic WhatsApp API error."""
    pass

class WhatsAppPermissionError(WhatsAppAPIError):
    """Error for phone number permission issues."""
    pass 