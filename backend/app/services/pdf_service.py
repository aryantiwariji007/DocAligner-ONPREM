from langchain_core.tools import tool
from datetime import datetime
from pathlib import Path
import subprocess
import shutil
import os
import json

# NO AI TOUCHES THESE TEMPLATES DIRECTLY
TEMPLATE_REGISTRY = {
    "compliance_report_v1": "backend/app/templates/compliance_report.tex",
}

def _render_latex_pdf(tex_content: str, output_dir: Path, base_filename: str) -> str:
    """Private helper to render a LaTeX document to PDF using Tectonic."""
    if shutil.which("tectonic") is None:
        raise RuntimeError("tectonic is not installed. Rebuild Docker containers.")

    try:
        tex_filename = f"{base_filename}.tex"
        pdf_filename = f"{base_filename}.pdf"
        
        tex_file = output_dir / tex_filename
        tex_file.write_text(tex_content)

        # Run Tectonic
        result = subprocess.run(
            ["tectonic", tex_filename, "--outdir", str(output_dir)],
            cwd=output_dir,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"Tectonic Error Output: {result.stderr}")
            raise RuntimeError(f"Tectonic failed with return code {result.returncode}")

        final_pdf = output_dir / pdf_filename
        if not final_pdf.exists():
            # Tectonic sometimes names it based on internal context, but usually matches tex_filename
            generated_pdf = output_dir / tex_filename.replace(".tex", ".pdf")
            if generated_pdf.exists():
                generated_pdf.rename(final_pdf)
            else:
                raise FileNotFoundError(f"PDF file was not generated at {final_pdf}")

        return str(final_pdf)
    except Exception as e:
        print(f"Error in _render_latex_pdf: {str(e)}")
        raise

@tool
def generate_fixed_pdf(template_id: str, content_json_str: str) -> str:
    """
    Generate a fixed-structure PDF using a predefined LaTeX template.
    The LLM provides only the content in JSON format; it never touches the LaTeX!

    Args:
        template_id: ID of the approved LaTeX template (e.g., 'compliance_report_v1')
        content_json_str: JSON string with structured content (e.g., '{"TITLE": "...", "ABSTRACT": "..."}')

    Returns:
        Path to the generated PDF document
    """
    if template_id not in TEMPLATE_REGISTRY:
        raise ValueError(f"Unapproved or missing template: {template_id}")

    try:
        # 1. Setup paths
        output_dir = Path("/tmp/pdf_outputs").absolute()
        output_dir.mkdir(exist_ok=True, parents=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_filename = f"{template_id}_{timestamp}"

        # 2. Load template
        template_path = Path(TEMPLATE_REGISTRY[template_id])
        if not template_path.exists():
             # Fallback check relative to app root
             template_path = Path("/app") / TEMPLATE_REGISTRY[template_id]
        
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found at {template_path}")

        latex_template = template_path.read_text()

        # 3. Parse content and inject safely
        content = json.loads(content_json_str)
        # We only replace placeholders that exist in the content
        final_latex = latex_template
        for key, value in content.items():
            placeholder = f"<<{key.upper()}>>"
            # Simple LaTeX escaping for common problematic chars
            safe_value = str(value).replace("_", "\\_").replace("#", "\\#").replace("%", "\\%").replace("$", "\\$")
            final_latex = final_latex.replace(placeholder, safe_value)

        # 4. Render
        return _render_latex_pdf(final_latex, output_dir, base_filename)

    except Exception as e:
        print(f"Error in generate_fixed_pdf: {str(e)}")
        raise

class PDFService:
    def create_structural_pdf(self, template_id: str, content_dict: dict) -> str:
        """High-level service method to generate a structural PDF."""
        return generate_fixed_pdf.invoke({
            "template_id": template_id,
            "content_json_str": json.dumps(content_dict)
        })

pdf_service = PDFService()
