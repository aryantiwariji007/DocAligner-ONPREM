from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import io
from pypdf import PdfReader
from backend.app.services.odf_service import odf_extractor

class BaseExtractor(ABC):
    @abstractmethod
    def extract_rules(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """Extracts rules/metadata from the given file content."""
        pass

class ODFExtractor(BaseExtractor):
    def extract_rules(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        # Delegate to existing ODF service
        # We wrap it to match the interface if needed, or just return its output
        try:
            return odf_extractor.extract_rules(file_content)
        except Exception as e:
            # Fallback if ODF parsing fails but it was an ODF extension
             return {
                "error": f"Failed to parse ODF: {str(e)}",
                "metadata": {"filename": filename}
            }

class PDFExtractor(BaseExtractor):
    def extract_rules(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        try:
            reader = PdfReader(io.BytesIO(file_content))
            info = reader.metadata
            
            metadata = {}
            if info:
                # pypdf metadata keys usually start with /, e.g. /Author
                for key, value in info.items():
                    clean_key = key.lstrip('/') if isinstance(key, str) else str(key)
                    metadata[clean_key] = str(value) if value else ""
            
            return {
                "metadata": metadata,
                "pages": len(reader.pages),
                "encrypted": reader.is_encrypted,
                "format": "PDF"
            }
        except Exception as e:
             return {
                "error": f"Failed to parse PDF: {str(e)}",
                "metadata": {"filename": filename},
                "format": "PDF"
            }

class GenericExtractor(BaseExtractor):
    def extract_rules(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        return {
            "metadata": {
                "filename": filename,
                "size_bytes": len(file_content)
            },
            "format": "GENERIC"
        }

class AIExtractor(BaseExtractor):
    async def extract_rules(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        from backend.app.services.ai_service import ai_service
        # 1. Get plain text first (no images for rule extraction)
        text = rule_extraction_factory.extract_text(file_content, filename, with_images=False)
        
        if ai_service.is_available():
            # Standard extraction often needs more context if the document is huge, 
            # but ai_service handles the truncation.
            return await ai_service.extract_standard(text, filename)
        return {"error": "AI Service unavailable"}

class RuleExtractionFactory:
    @staticmethod
    def get_extractor(filename: str) -> BaseExtractor:
        ext = filename.lower().split('.')[-1] if '.' in filename else ""
        
        if ext in ['odt', 'ott', 'odm']:
            return ODFExtractor()
        elif ext == 'pdf':
            return PDFExtractor()
        else:
            return GenericExtractor()
    
    @staticmethod
    async def extract_rules_async(file_content: bytes, filename: str, use_ai: bool = True) -> Dict[str, Any]:
        from backend.app.services.ai_service import ai_service
        if use_ai and ai_service.is_available():
            extractor = AIExtractor()
            return await extractor.extract_rules(file_content, filename)
        
        # Fallback to sync extractors
        extractor = RuleExtractionFactory.get_extractor(filename)
        return extractor.extract_rules(file_content, filename)

    @staticmethod
    def extract_text(file_content: bytes, filename: str, with_images: bool = False) -> str:
        """Extracts plain text. Optionally includes embedded images as base64."""
        import io
        import base64
        
        ext = filename.lower().split('.')[-1] if '.' in filename else ""
        text = ""
        
        try:
            if ext == 'pdf':
                try:
                    import fitz
                    doc = fitz.open(stream=file_content, filetype="pdf")
                    pages_text = []
                    for page_index in range(len(doc)):
                        page = doc[page_index]
                        p_text = page.get_text()
                        
                        if with_images:
                            # Extract images only if requested (for detailed preview, not for LLM)
                            image_list = page.get_images(full=True)
                            for img_index, img in enumerate(image_list):
                                xref = img[0]
                                base_image = doc.extract_image(xref)
                                image_bytes = base_image["image"]
                                image_ext = base_image["ext"]
                                if len(image_bytes) < 500000:
                                    b64 = base64.b64encode(image_bytes).decode("utf-8")
                                    data_uri = f"data:image/{image_ext};base64,{b64}"
                                    p_text += f"\n\n![Original Image {page_index+1}-{img_index+1}]({data_uri})\n\n"
                                else:
                                    p_text += f"\n\n![Large Image Placeholder: {image_ext}]\n\n"
                        pages_text.append(p_text)
                    text = "\n---\n".join(pages_text)
                except ImportError:
                    # Fallback to pypdf if fitz is missing
                    from pypdf import PdfReader
                    reader = PdfReader(io.BytesIO(file_content))
                    text = "\n".join([page.extract_text() for page in reader.pages])
                 
            elif ext in ['docx', 'doc']:
                 try:
                     import mammoth
                     import markdownify
                     result = mammoth.convert_to_html(io.BytesIO(file_content))
                     html = result.value
                     text = markdownify.markdownify(html)
                 except ImportError:
                     text = file_content.decode('utf-8', errors='ignore')
            elif ext in ['txt', 'md', 'json', 'xml', 'html', 'css', 'js', 'py', 'java', 'c', 'cpp']:
                 text = file_content.decode('utf-8', errors='ignore')
            else:
                 text = file_content.decode('utf-8', errors='ignore')
                 
            return text
        except Exception as e:
            return f"Error extracting text: {str(e)}"

rule_extraction_factory = RuleExtractionFactory()
