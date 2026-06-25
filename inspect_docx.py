import zipfile
import xml.etree.ElementTree as ET

def get_docx_text(path):
    try:
        with zipfile.ZipFile(path) as docx:
            tree = ET.parse(docx.open('word/document.xml'))
            root = tree.getroot()
            text = []
            
            # The namespace for Word processingML elements
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            
            # Find all paragraph elements and extract text from text runs
            for paragraph in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                p_text = []
                for text_run in paragraph.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'):
                    p_text.append(text_run.text)
                if p_text:
                    text.append(''.join(p_text))
            return '\n'.join(text)
    except Exception as e:
        return f"Error reading docx: {e}"

text = get_docx_text("datesets folder/Ghana_Agricultural_Data_Source_Documentation.docx")
print("=== DOCUMENTATION CONTENT ===")
print(text[:4000]) # Print first 4000 chars
