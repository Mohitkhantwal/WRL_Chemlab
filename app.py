"""
Referral Assay Laboratory (RAL) - Laboratory Information Management System (LIMS)
Production-Ready Streamlit Application

TECH STACK:
- Frontend: Streamlit (Mobile responsive)
- Database: Google Sheets API (gspread and oauth2client)
- Image Storage: Google Drive API (google-api-python-client)
- Document Parsing/OCR: Gemini API (google-generativeai)
- PDF Generation: fpdf
"""

import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
import google.generativeai as genai
from fpdf import FPDF
import json
import io
import base64
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import pandas as pd
from PIL import Image
import os

# ============================================================================
# PAGE CONFIGURATION & INITIALIZATION
# ============================================================================

st.set_page_config(
    page_title="RAL LIMS",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": "Referral Assay Laboratory (RAL) - Laboratory Information Management System",
        "Get Help": "mailto:admin@ral-lab.com"
    }
)

# Custom CSS for mobile responsiveness
st.markdown("""
    <style>
        @media (max-width: 768px) {
            .main {
                padding: 0.5rem 0;
            }
            .stButton > button {
                width: 100%;
            }
            .stSelectbox, .stTextInput, .stNumberInput {
                width: 100%;
            }
        }
        .header-title {
            text-align: center;
            color: #1f77b4;
            font-size: 2.5rem;
            font-weight: bold;
            margin-bottom: 0.5rem;
        }
        .subheader {
            text-align: center;
            color: #555;
            font-size: 1rem;
            margin-bottom: 2rem;
        }
        .success-box {
            background-color: #d4edda;
            border: 1px solid #c3e6cb;
            border-radius: 5px;
            padding: 1rem;
            margin: 1rem 0;
            color: #155724;
        }
        .error-box {
            background-color: #f8d7da;
            border: 1px solid #f5c6cb;
            border-radius: 5px;
            padding: 1rem;
            margin: 1rem 0;
            color: #721c24;
        }
        .info-box {
            background-color: #d1ecf1;
            border: 1px solid #bee5eb;
            border-radius: 5px;
            padding: 1rem;
            margin: 1rem 0;
            color: #0c5460;
        }
    </style>
    """, unsafe_allow_html=True)

# ============================================================================
# GOOGLE SHEETS & DRIVE AUTHENTICATION
# ============================================================================

@st.cache_resource
def get_google_credentials():
    """Retrieve Google Service Account credentials from Streamlit secrets."""
    try:
        service_account_info = st.secrets["google_service_account"]
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=[
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
        )
        return credentials
    except Exception as e:
        st.error(f"❌ Failed to load Google credentials: {str(e)}")
        st.error("Please configure .streamlit/secrets.toml with your Google Service Account credentials.")
        st.stop()

@st.cache_resource
def get_gspread_client():
    """Create and return an authenticated gspread client."""
    try:
        scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        service_account_info = st.secrets["google_service_account"]
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(
            service_account_info,
            scopes=scope
        )
        client = gspread.authorize(credentials)
        return client
    except Exception as e:
        st.error(f"❌ Failed to authenticate gspread: {str(e)}")
        st.stop()

@st.cache_resource
def get_drive_service():
    """Create and return an authenticated Google Drive service."""
    try:
        credentials = get_google_credentials()
        drive_service = build('drive', 'v3', credentials=credentials)
        return drive_service
    except Exception as e:
        st.error(f"❌ Failed to initialize Drive service: {str(e)}")
        st.stop()

@st.cache_resource
def get_sheets_service():
    """Create and return an authenticated Google Sheets service."""
    try:
        credentials = get_google_credentials()
        sheets_service = build('sheets', 'v4', credentials=credentials)
        return sheets_service
    except Exception as e:
        st.error(f"❌ Failed to initialize Sheets service: {str(e)}")
        st.stop()

# ============================================================================
# GEMINI API INITIALIZATION
# ============================================================================

def initialize_gemini():
    """Initialize Gemini API with the API key from Streamlit secrets."""
    try:
        gemini_api_key = st.secrets.get("gemini_api_key")
        if not gemini_api_key:
            st.error("❌ Gemini API key not found in secrets. Please configure .streamlit/secrets.toml")
            st.stop()
        genai.configure(api_key=gemini_api_key)
    except Exception as e:
        st.error(f"❌ Failed to initialize Gemini API: {str(e)}")
        st.stop()

# ============================================================================
# GOOGLE SHEETS DATABASE OPERATIONS
# ============================================================================

def get_spreadsheet():
    """Fetch and return the Google Spreadsheet object."""
    try:
        client = get_gspread_client()
        spreadsheet_id = st.secrets.get("spreadsheet_id")
        if not spreadsheet_id:
            st.error("❌ Spreadsheet ID not found in secrets.")
            st.stop()
        spreadsheet = client.open_by_key(spreadsheet_id)
        return spreadsheet
    except Exception as e:
        st.error(f"❌ Failed to access spreadsheet: {str(e)}")
        st.stop()

def append_to_samples_sheet(sample_id: str, is_code: str, raw_ocr_text: str) -> bool:
    """Append a new row to the 'Samples' worksheet."""
    try:
        spreadsheet = get_spreadsheet()
        samples_sheet = spreadsheet.worksheet("Samples")
        
        date_added = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_row = [sample_id, is_code, date_added, raw_ocr_text]
        
        samples_sheet.append_row(new_row)
        return True
    except Exception as e:
        st.error(f"❌ Error appending to Samples sheet: {str(e)}")
        return False

def get_pending_samples() -> List[str]:
    """Fetch all Sample IDs from the 'Samples' worksheet."""
    try:
        spreadsheet = get_spreadsheet()
        samples_sheet = spreadsheet.worksheet("Samples")
        all_data = samples_sheet.get_all_records()
        
        sample_ids = [row.get("Sample_ID") for row in all_data if row.get("Sample_ID")]
        return sorted(list(set(sample_ids)))
    except Exception as e:
        st.error(f"❌ Error fetching samples: {str(e)}")
        return []

def get_sample_is_code(sample_id: str) -> Optional[str]:
    """Retrieve the IS_Code for a given Sample_ID."""
    try:
        spreadsheet = get_spreadsheet()
        samples_sheet = spreadsheet.worksheet("Samples")
        all_data = samples_sheet.get_all_records()
        
        for row in all_data:
            if row.get("Sample_ID") == sample_id:
                return row.get("IS_Code")
        return None
    except Exception as e:
        st.error(f"❌ Error fetching IS_Code: {str(e)}")
        return None

def get_parameters_for_is_code(is_code: str) -> List[Dict]:
    """Fetch all test parameters for a given IS_Code."""
    try:
        spreadsheet = get_spreadsheet()
        parameters_sheet = spreadsheet.worksheet("IS_Parameters")
        all_data = parameters_sheet.get_all_records()
        
        parameters = [row for row in all_data if row.get("IS_Code") == is_code]
        return parameters
    except Exception as e:
        st.error(f"❌ Error fetching parameters: {str(e)}")
        return []

def append_to_test_results(result_id: str, sample_id: str, parameter_id: str, 
                           result_value: str, conformity: str, image_drive_link: str = "") -> bool:
    """Append a new row to the 'Test_Results' worksheet."""
    try:
        spreadsheet = get_spreadsheet()
        test_results_sheet = spreadsheet.worksheet("Test_Results")
        
        new_row = [result_id, sample_id, parameter_id, result_value, conformity, image_drive_link]
        test_results_sheet.append_row(new_row)
        return True
    except Exception as e:
        st.error(f"❌ Error appending to Test_Results sheet: {str(e)}")
        return False

def get_test_results_for_sample(sample_id: str) -> List[Dict]:
    """Fetch all test results for a given Sample_ID."""
    try:
        spreadsheet = get_spreadsheet()
        test_results_sheet = spreadsheet.worksheet("Test_Results")
        all_data = test_results_sheet.get_all_records()
        
        results = [row for row in all_data if row.get("Sample_ID") == sample_id]
        return results
    except Exception as e:
        st.error(f"❌ Error fetching test results: {str(e)}")
        return []

def get_all_is_parameters() -> List[Dict]:
    """Fetch all parameters from the IS_Parameters worksheet."""
    try:
        spreadsheet = get_spreadsheet()
        parameters_sheet = spreadsheet.worksheet("IS_Parameters")
        all_data = parameters_sheet.get_all_records()
        return all_data
    except Exception as e:
        st.error(f"❌ Error fetching all parameters: {str(e)}")
        return []

# ============================================================================
# GOOGLE DRIVE OPERATIONS
# ============================================================================

def upload_image_to_drive(image_data: bytes, filename: str) -> Optional[str]:
    """Upload an image to Google Drive and return the public sharing link."""
    try:
        drive_service = get_drive_service()
        folder_id = st.secrets.get("drive_folder_id")
        
        if not folder_id:
            st.warning("⚠️ Drive folder ID not configured. Image will not be saved.")
            return None
        
        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        
        media = MediaIoBaseUpload(io.BytesIO(image_data), mimetype='image/jpeg')
        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        
        file_id = file.get('id')
        
        # Make the file publicly accessible
        drive_service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
        
        public_link = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
        return public_link
    except Exception as e:
        st.error(f"❌ Error uploading image to Drive: {str(e)}")
        return None

# ============================================================================
# GEMINI API OCR PARSING
# ============================================================================

def parse_pdf_with_gemini(pdf_bytes: bytes) -> Tuple[Optional[str], Optional[str], str]:
    """
    Use Gemini API to extract Sample_ID and IS_Code from a PDF document.
    Returns: (sample_id, is_code, raw_ocr_text)
    """
    try:
        initialize_gemini()
        
        # Convert PDF bytes to base64 for API
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
        
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = """
        Please analyze this laboratory test request document and extract the following information:
        1. Sample ID (any identifier like 'Sample-001', 'S-123', etc.)
        2. IS Code (Indian Standard code like 'IS 5405', 'IS 1418', 'IS 2113', etc.)
        
        Return the response in this exact format:
        SAMPLE_ID: [extracted_id]
        IS_CODE: [extracted_code]
        
        If any information is not found, write 'NOT_FOUND' for that field.
        Also provide the complete raw OCR text of the document.
        
        RAW_OCR_TEXT:
        [complete text of the document]
        """
        
        response = model.generate_content([
            {
                "mime_type": "application/pdf",
                "data": pdf_base64
            },
            prompt
        ])
        
        response_text = response.text
        
        # Parse the response
        lines = response_text.split('\n')
        sample_id = None
        is_code = None
        raw_ocr_text = response_text
        
        for line in lines:
            if line.startswith("SAMPLE_ID:"):
                sample_id = line.replace("SAMPLE_ID:", "").strip()
                if sample_id.upper() == "NOT_FOUND":
                    sample_id = None
            elif line.startswith("IS_CODE:"):
                is_code = line.replace("IS_CODE:", "").strip()
                if is_code.upper() == "NOT_FOUND":
                    is_code = None
        
        return sample_id, is_code, raw_ocr_text
    except Exception as e:
        st.error(f"❌ Error parsing PDF with Gemini: {str(e)}")
        return None, None, str(e)

# ============================================================================
# PDF REPORT GENERATION
# ============================================================================

class RALReportPDF(FPDF):
    """Custom PDF class for generating RAL laboratory reports."""
    
    def __init__(self):
        super().__init__()
        self.WIDTH = 210
        self.HEIGHT = 297
        
    def header(self):
        """Generate the PDF header with RAL branding."""
        self.set_font("Arial", "B", 20)
        self.cell(0, 10, "Referral Assay Laboratory (RAL)", 0, 1, "C")
        
        self.set_font("Arial", "", 10)
        self.cell(0, 5, "Laboratory Information Management System (LIMS) Report", 0, 1, "C")
        
        self.set_font("Arial", "", 9)
        self.cell(0, 5, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", 0, 1, "C")
        
        self.ln(5)
        self.line(10, self.get_y(), self.WIDTH - 10, self.get_y())
        self.ln(5)
    
    def footer(self):
        """Generate the PDF footer."""
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}", 0, 0, "C")
    
    def add_sample_section(self, sample_id: str, is_code: str):
        """Add sample information section."""
        self.set_font("Arial", "B", 12)
        self.cell(0, 8, "Sample Information", 0, 1)
        
        self.set_font("Arial", "", 10)
        self.cell(50, 6, "Sample ID:")
        self.cell(0, 6, sample_id, 0, 1)
        
        self.cell(50, 6, "IS Code:")
        self.cell(0, 6, is_code, 0, 1)
        
        self.cell(50, 6, "Test Date:")
        self.cell(0, 6, datetime.now().strftime('%Y-%m-%d'), 0, 1)
        
        self.ln(5)
    
    def add_results_table(self, results_data: List[Dict]):
        """Add test results table to the PDF."""
        self.set_font("Arial", "B", 12)
        self.cell(0, 8, "Test Results", 0, 1)
        
        self.set_font("Arial", "B", 9)
        self.set_fill_color(200, 220, 255)
        
        col_widths = [40, 50, 35, 35, 30]
        headers = ["Parameter", "Test Name", "Limits", "Result", "Conformity"]
        
        for i, header in enumerate(headers):
            self.cell(col_widths[i], 8, header, 1, 0, "C", fill=True)
        self.ln()
        
        self.set_font("Arial", "", 9)
        for result in results_data:
            parameter_id = result.get("Parameter_ID", "N/A")[:10]
            test_name = str(result.get("Test_Name", "N/A"))[:30]
            limits = str(result.get("Limits", "N/A"))[:20]
            result_value = str(result.get("Result_Value", "N/A"))[:20]
            conformity = result.get("Conformity", "N/A")[:15]
            
            self.cell(col_widths[0], 6, parameter_id, 1)
            self.cell(col_widths[1], 6, test_name, 1)
            self.cell(col_widths[2], 6, limits, 1)
            self.cell(col_widths[3], 6, result_value, 1)
            self.cell(col_widths[4], 6, conformity, 1)
            self.ln()
        
        self.ln(5)
    
    def add_footer_section(self):
        """Add footer/certification section."""
        self.set_font("Arial", "B", 10)
        self.cell(0, 8, "Certification", 0, 1)
        
        self.set_font("Arial", "", 8)
        footer_text = "This report has been generated by the RAL LIMS system. All test parameters comply with respective Indian Standards (IS codes). For detailed information, please contact the laboratory."
        self.multi_cell(0, 4, footer_text)

def generate_pdf_report(sample_id: str, is_code: str, results_data: List[Dict]) -> Optional[bytes]:
    """Generate a professional PDF laboratory report."""
    try:
        pdf = RALReportPDF()
        pdf.add_page()
        
        pdf.add_sample_section(sample_id, is_code)
        pdf.add_results_table(results_data)
        pdf.add_footer_section()
        
        pdf_output = pdf.output(dest='S')
        if isinstance(pdf_output, str):
            pdf_output = pdf_output.encode('latin-1')
        
        return pdf_output
    except Exception as e:
        st.error(f"❌ Error generating PDF report: {str(e)}")
        return None

# ============================================================================
# PAGE: NEW INTAKE
# ============================================================================

def page_new_intake():
    """PAGE 1: New Intake - OCR/Scraping Engine for Test Request PDFs"""
    st.markdown('<div class="header-title">📄 New Intake</div>', unsafe_allow_html=True)
    st.markdown('<div class="subheader">Extract and Register New Test Requests</div>', unsafe_allow_html=True)
    
    st.markdown("""
    Upload a PDF test request document. The system will use AI (Gemini) to extract:
    - **Sample ID**: Unique identifier for the sample
    - **IS Code**: Indian Standard code (e.g., IS 5405, IS 1418, IS 2113)
    """)
    
    uploaded_file = st.file_uploader(
        "📤 Upload Test Request PDF",
        type=["pdf"],
        help="Select a PDF file containing the test request"
    )
    
    if uploaded_file is not None:
        st.info(f"✅ File selected: {uploaded_file.name}")
        
        # Read the PDF file
        pdf_bytes = uploaded_file.read()
        
        if st.button("🔍 Parse Document with AI", key="parse_pdf"):
            with st.spinner("🔄 Parsing PDF with Gemini API..."):
                sample_id, is_code, raw_ocr_text = parse_pdf_with_gemini(pdf_bytes)
            
            if sample_id and is_code:
                st.session_state.parsed_sample_id = sample_id
                st.session_state.parsed_is_code = is_code
                st.session_state.parsed_raw_ocr = raw_ocr_text
                st.session_state.show_confirmation = True
            else:
                st.markdown('<div class="error-box">❌ Could not extract required information. Please ensure the PDF contains Sample ID and IS Code.</div>', unsafe_allow_html=True)
    
    # Show confirmation form
    if st.session_state.get("show_confirmation", False):
        st.markdown("---")
        st.markdown('<div class="info-box">✓ Document Parsed Successfully</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            sample_id_input = st.text_input(
                "Sample ID",
                value=st.session_state.parsed_sample_id,
                help="Unique identifier for this sample"
            )
        
        with col2:
            is_code_input = st.text_input(
                "IS Code",
                value=st.session_state.parsed_is_code,
                help="Indian Standard code (e.g., IS 5405)"
            )
        
        with st.expander("📋 View Extracted Raw OCR Text"):
            st.text_area(
                "Raw OCR Text",
                value=st.session_state.parsed_raw_ocr,
                height=200,
                disabled=True
            )
        
        col1, col2, col3 = st.columns([1, 1, 2])
        
        with col1:
            if st.button("✅ Submit", key="submit_intake"):
                if not sample_id_input or not is_code_input:
                    st.error("❌ Please fill in all required fields.")
                else:
                    success = append_to_samples_sheet(
                        sample_id_input,
                        is_code_input,
                        st.session_state.parsed_raw_ocr
                    )
                    
                    if success:
                        st.markdown(f'<div class="success-box">✅ Sample "{sample_id_input}" successfully registered to the database!</div>', unsafe_allow_html=True)
                        st.session_state.show_confirmation = False
                        st.session_state.parsed_sample_id = None
                        st.session_state.parsed_is_code = None
                        st.session_state.parsed_raw_ocr = None
                        st.balloons()
                    else:
                        st.markdown('<div class="error-box">❌ Failed to save to database. Please try again.</div>', unsafe_allow_html=True)
        
        with col2:
            if st.button("❌ Cancel", key="cancel_intake"):
                st.session_state.show_confirmation = False
                st.rerun()

# ============================================================================
# PAGE: LAB FLOOR
# ============================================================================

def page_lab_floor():
    """PAGE 2: Lab Floor - Mobile Testing UI for Recording Test Results"""
    st.markdown('<div class="header-title">🧪 Lab Floor Testing</div>', unsafe_allow_html=True)
    st.markdown('<div class="subheader">Record Test Results and Capture Evidence</div>', unsafe_allow_html=True)
    
    # Fetch all pending samples
    pending_samples = get_pending_samples()
    
    if not pending_samples:
        st.warning("⚠️ No samples found in the database. Please add samples via 'New Intake' page.")
        return
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        selected_sample = st.selectbox(
            "Select Sample",
            options=pending_samples,
            help="Choose a sample to test"
        )
    
    with col2:
        if st.button("🔄 Refresh Samples", key="refresh_samples_lab"):
            st.rerun()
    
    if selected_sample:
        # Get IS_Code for the selected sample
        is_code = get_sample_is_code(selected_sample)
        
        if not is_code:
            st.error(f"❌ Could not find IS_Code for sample {selected_sample}")
            return
        
        st.info(f"📍 Sample: **{selected_sample}** | IS Code: **{is_code}**")
        
        # Get parameters for this IS_Code
        parameters = get_parameters_for_is_code(is_code)
        
        if not parameters:
            st.warning(f"⚠️ No test parameters found for IS Code {is_code}. Please configure parameters in the database.")
            return
        
        st.markdown(f"### Testing Parameters ({len(parameters)} tests)")
        
        # Initialize session state for test results form
        if "test_results_form" not in st.session_state:
            st.session_state.test_results_form = {}
        
        # Create forms for each parameter
        for idx, param in enumerate(parameters):
            param_id = param.get("Parameter_ID", f"PARAM_{idx}")
            test_name = param.get("Test_Name", "Unknown Test")
            limits = param.get("Limits", "N/A")
            
            with st.expander(f"✅ {test_name} (ID: {param_id})", expanded=(idx == 0)):
                col1, col2 = st.columns([1, 1])
                
                with col1:
                    st.markdown(f"**Limits:** {limits}")
                    result_value = st.text_input(
                        "Observed Result",
                        key=f"result_{param_id}",
                        help="Enter the measured value"
                    )
                
                with col2:
                    conformity = st.radio(
                        "Conformity Status",
                        options=["Conforms", "Does Not Conform", "N/A"],
                        key=f"conformity_{param_id}",
                        horizontal=True
                    )
                
                # Camera input for evidence
                camera_image = st.camera_input(
                    "📸 Capture Evidence",
                    key=f"camera_{param_id}",
                    help="Take a photo as evidence for this test"
                )
                
                # Store form data in session state
                st.session_state.test_results_form[param_id] = {
                    "test_name": test_name,
                    "limits": limits,
                    "result_value": result_value,
                    "conformity": conformity,
                    "camera_image": camera_image
                }
        
        st.markdown("---")
        
        if st.button("💾 Save All Test Results", key="save_lab_floor_results"):
            all_saved = True
            saved_count = 0
            
            with st.spinner("Saving test results..."):
                for param_id, test_data in st.session_state.test_results_form.items():
                    result_value = test_data.get("result_value", "")
                    conformity = test_data.get("conformity", "N/A")
                    camera_image = test_data.get("camera_image")
                    
                    # If no result value, skip this parameter
                    if not result_value:
                        continue
                    
                    image_drive_link = ""
                    
                    # Upload image to Drive if captured
                    if camera_image is not None:
                        # Convert camera image to bytes
                        image_pil = Image.open(camera_image)
                        image_byte_arr = io.BytesIO()
                        image_pil.save(image_byte_arr, format='JPEG')
                        image_byte_arr.seek(0)
                        
                        filename = f"{selected_sample}_{param_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                        image_drive_link = upload_image_to_drive(image_byte_arr.getvalue(), filename)
                    
                    # Generate Result_ID
                    result_id = f"RES_{selected_sample}_{param_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    
                    # Append to Test_Results sheet
                    success = append_to_test_results(
                        result_id,
                        selected_sample,
                        param_id,
                        result_value,
                        conformity,
                        image_drive_link if image_drive_link else ""
                    )
                    
                    if success:
                        saved_count += 1
                    else:
                        all_saved = False
            
            if all_saved and saved_count > 0:
                st.markdown(f'<div class="success-box">✅ Successfully saved {saved_count} test results!</div>', unsafe_allow_html=True)
                st.balloons()
                # Clear session state
                st.session_state.test_results_form = {}
            elif saved_count > 0:
                st.warning(f"⚠️ Saved {saved_count} test results but some entries failed.")
            else:
                st.warning("⚠️ No test results were saved. Please fill in at least one result value.")

# ============================================================================
# PAGE: REPORTS
# ============================================================================

def page_reports():
    """PAGE 3: Reports - PDF Generation and Download"""
    st.markdown('<div class="header-title">📊 Laboratory Reports</div>', unsafe_allow_html=True)
    st.markdown('<div class="subheader">Generate and Download Official Lab Reports</div>', unsafe_allow_html=True)
    
    # Fetch all samples that have test results
    all_samples = get_pending_samples()
    
    if not all_samples:
        st.warning("⚠️ No samples found. Please add samples via 'New Intake' page.")
        return
    
    # Filter samples with completed tests
    samples_with_results = []
    for sample_id in all_samples:
        results = get_test_results_for_sample(sample_id)
        if results:
            samples_with_results.append(sample_id)
    
    if not samples_with_results:
        st.info("ℹ️ No completed tests found. Please record test results on the 'Lab Floor' page.")
        return
    
    selected_sample = st.selectbox(
        "Select a Sample to Generate Report",
        options=samples_with_results,
        help="Choose a completed sample"
    )
    
    if selected_sample:
        # Get sample details
        is_code = get_sample_is_code(selected_sample)
        
        # Get test results
        test_results_raw = get_test_results_for_sample(selected_sample)
        
        # Get all parameters for reference
        all_parameters = get_all_is_parameters()
        param_dict = {param.get("Parameter_ID"): param for param in all_parameters}
        
        # Merge test results with parameter information
        test_results_merged = []
        for result in test_results_raw:
            param_id = result.get("Parameter_ID")
            if param_id in param_dict:
                merged = {**result, **param_dict[param_id]}
                test_results_merged.append(merged)
            else:
                test_results_merged.append(result)
        
        # Display results in a table
        st.markdown(f"### Sample: {selected_sample} | IS Code: {is_code}")
        
        if test_results_merged:
            df_display = pd.DataFrame(test_results_merged)
            
            # Select relevant columns for display
            display_columns = ["Parameter_ID", "Test_Name", "Limits", "Result_Value", "Conformity"]
            available_columns = [col for col in display_columns if col in df_display.columns]
            
            st.dataframe(
                df_display[available_columns],
                use_container_width=True,
                height=300
            )
            
            st.markdown("---")
            
            # Generate PDF Report
            if st.button("📄 Generate Official PDF Report", key="generate_pdf_report"):
                with st.spinner("Generating PDF report..."):
                    pdf_bytes = generate_pdf_report(selected_sample, is_code, test_results_merged)
                
                if pdf_bytes:
                    st.markdown('<div class="success-box">✅ PDF Report Generated Successfully!</div>', unsafe_allow_html=True)
                    
                    st.download_button(
                        label="⬇️ Download PDF Report",
                        data=pdf_bytes,
                        file_name=f"RAL_Report_{selected_sample}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                        mime="application/pdf",
                        key="download_pdf"
                    )
                else:
                    st.markdown('<div class="error-box">❌ Failed to generate PDF report.</div>', unsafe_allow_html=True)
        else:
            st.warning("⚠️ No test results found for this sample.")

# ============================================================================
# SIDEBAR NAVIGATION
# ============================================================================

def main():
    """Main application with sidebar navigation."""
    
    # Initialize session state
    if "show_confirmation" not in st.session_state:
        st.session_state.show_confirmation = False
    if "parsed_sample_id" not in st.session_state:
        st.session_state.parsed_sample_id = None
    if "parsed_is_code" not in st.session_state:
        st.session_state.parsed_is_code = None
    if "parsed_raw_ocr" not in st.session_state:
        st.session_state.parsed_raw_ocr = None
    if "test_results_form" not in st.session_state:
        st.session_state.test_results_form = {}
    
    # Sidebar navigation
    with st.sidebar:
        st.markdown('<div style="text-align: center; font-size: 1.8rem; margin-bottom: 1rem;">🧪 RAL LIMS</div>', unsafe_allow_html=True)
        st.markdown("### Navigation")
        
        page = st.radio(
            "Select Page",
            options=["New Intake", "Lab Floor", "Reports"],
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        
        st.markdown("### System Information")
        st.caption("**Application:** RAL LIMS v1.0")
        st.caption("**Version:** Production Ready")
        st.caption(f"**Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        
        st.markdown("---")
        
        st.markdown("### Help & Support")
        st.caption("For technical support, contact:")
        st.caption("📧 admin@ral-lab.com")
        st.caption("📞 +91-XXX-XXXXXXX")
    
    # Route to pages
    if page == "New Intake":
        page_new_intake()
    elif page == "Lab Floor":
        page_lab_floor()
    elif page == "Reports":
        page_reports()

if __name__ == "__main__":
    main()
