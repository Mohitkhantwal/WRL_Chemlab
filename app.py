"""
Referral Assay Laboratory (RAL) - Laboratory Information Management System (LIMS)
A complete, mobile-responsive Streamlit web application for laboratory sample management,
testing, and report generation.

REQUIREMENTS.TXT:
streamlit==1.28.1
gspread==5.10.0
oauth2client==4.1.3
google-api-python-client==2.99.0
google-generativeai==0.3.0
google-auth-oauthlib==1.1.0
google-auth-httplib2==0.2.0
fpdf==1.7.2
python-dotenv==1.0.0
Pillow==10.0.0

Deployment: Deploy on Streamlit Cloud with secrets configured in .streamlit/secrets.toml
"""

import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
import google.generativeai as genai
from fpdf import FPDF
import io
import json
import base64
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import pandas as pd
from PIL import Image

# ============================================================================
# PAGE CONFIGURATION & INITIALIZATION
# ============================================================================

st.set_page_config(
    page_title="RAL LIMS",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": "Referral Assay Laboratory - LIMS v1.0"
    }
)

# Custom CSS for mobile responsiveness
st.markdown("""
    <style>
    @media (max-width: 768px) {
        .main {
            padding: 0px;
        }
        .stCameraInput {
            width: 100%;
        }
    }
    .stButton > button {
        width: 100%;
    }
    .stDataFrame {
        width: 100%;
    }
    </style>
    """, unsafe_allow_html=True)

# ============================================================================
# GOOGLE SHEETS & DRIVE API INITIALIZATION
# ============================================================================

@st.cache_resource
def init_gspread_client():
    """Initialize Google Sheets client with service account credentials."""
    try:
        creds_dict = st.secrets["google_sheets"]["credentials"]
        scope = ['https://spreadsheets.google.com/auth', 
                 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"Failed to initialize Google Sheets client: {str(e)}")
        return None

@st.cache_resource
def init_drive_client():
    """Initialize Google Drive client with service account credentials."""
    try:
        creds_dict = st.secrets["google_sheets"]["credentials"]
        credentials = Credentials.from_service_account_info(
            creds_dict,
            scopes=['https://www.googleapis.com/auth/drive']
        )
        return build('drive', 'v3', credentials=credentials)
    except Exception as e:
        st.error(f"Failed to initialize Google Drive client: {str(e)}")
        return None

@st.cache_resource
def init_gemini_client():
    """Initialize Gemini API client."""
    try:
        api_key = st.secrets["gemini"]["api_key"]
        genai.configure(api_key=api_key)
        return genai.GenerativeModel('gemini-pro-vision')
    except Exception as e:
        st.error(f"Failed to initialize Gemini client: {str(e)}")
        return None

# Initialize clients
gspread_client = init_gspread_client()
drive_client = init_drive_client()
gemini_model = init_gemini_client()

# ============================================================================
# GOOGLE SHEETS HELPER FUNCTIONS
# ============================================================================

def get_sheet_data(sheet_name: str, worksheet_name: str) -> pd.DataFrame:
    """Fetch data from a specific Google Sheet worksheet."""
    try:
        if not gspread_client:
            st.error("Google Sheets client not initialized")
            return pd.DataFrame()
        
        sheet = gspread_client.open(sheet_name)
        worksheet = sheet.worksheet(worksheet_name)
        data = worksheet.get_all_values()
        
        if len(data) == 0:
            return pd.DataFrame()
        
        headers = data[0]
        rows = data[1:]
        df = pd.DataFrame(rows, columns=headers)
        return df
    except Exception as e:
        st.error(f"Error fetching data from {worksheet_name}: {str(e)}")
        return pd.DataFrame()

def append_to_sheet(sheet_name: str, worksheet_name: str, row_data: List) -> bool:
    """Append a new row to a Google Sheet worksheet."""
    try:
        if not gspread_client:
            st.error("Google Sheets client not initialized")
            return False
        
        sheet = gspread_client.open(sheet_name)
        worksheet = sheet.worksheet(worksheet_name)
        worksheet.append_row(row_data)
        return True
    except Exception as e:
        st.error(f"Error appending to {worksheet_name}: {str(e)}")
        return False

def update_sheet_cell(sheet_name: str, worksheet_name: str, row: int, col: int, value: str) -> bool:
    """Update a specific cell in a Google Sheet."""
    try:
        if not gspread_client:
            st.error("Google Sheets client not initialized")
            return False
        
        sheet = gspread_client.open(sheet_name)
        worksheet = sheet.worksheet(worksheet_name)
        worksheet.update_cell(row, col, value)
        return True
    except Exception as e:
        st.error(f"Error updating cell in {worksheet_name}: {str(e)}")
        return False

# ============================================================================
# GOOGLE DRIVE HELPER FUNCTIONS
# ============================================================================

def upload_image_to_drive(image_file, folder_id: str) -> Optional[str]:
    """Upload an image file to Google Drive and return the shareable link."""
    try:
        if not drive_client:
            st.error("Google Drive client not initialized")
            return None
        
        file_metadata = {
            'name': f"evidence_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg",
            'parents': [folder_id]
        }
        
        media = MediaIoBaseUpload(image_file, mimetype='image/jpeg', resumable=True)
        file = drive_client.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        
        file_id = file.get('id')
        
        # Make file publicly accessible
        drive_client.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
        
        public_url = f"https://drive.google.com/uc?id={file_id}&export=view"
        return public_url
    except Exception as e:
        st.error(f"Error uploading image to Drive: {str(e)}")
        return None

# ============================================================================
# GEMINI API HELPER FUNCTIONS
# ============================================================================

def extract_data_from_pdf(pdf_file) -> Dict:
    """Extract Sample_ID and IS_Code from PDF using Gemini API."""
    try:
        if not gemini_model:
            st.error("Gemini model not initialized")
            return {}
        
        # Convert PDF to bytes
        pdf_bytes = pdf_file.read()
        
        # Prepare prompt for extraction
        prompt = """
        Analyze this laboratory test request PDF and extract the following information:
        1. Sample ID (any identifier starting with 'S' or containing 'Sample')
        2. IS Code (Indian Standard code like IS 5405, IS 1418, IS 2113)
        3. Any additional relevant information
        
        Provide the response in JSON format with keys: sample_id, is_code, raw_text
        """
        
        # Use Gemini to process PDF content
        response = gemini_model.generate_content([
            prompt,
            {"mime_type": "application/pdf", "data": pdf_bytes}
        ])
        
        response_text = response.text
        
        # Parse response to extract structured data
        extracted_data = {
            "sample_id": extract_json_field(response_text, "sample_id"),
            "is_code": extract_json_field(response_text, "is_code"),
            "raw_ocr_text": response_text
        }
        
        return extracted_data
    except Exception as e:
        st.error(f"Error extracting data from PDF: {str(e)}")
        return {}

def extract_json_field(response_text: str, field_name: str) -> str:
    """Helper function to extract JSON field from Gemini response."""
    try:
        import re
        pattern = f'"{field_name}"\\s*:\\s*"([^"]*)"'
        match = re.search(pattern, response_text)
        if match:
            return match.group(1)
        return ""
    except:
        return ""

# ============================================================================
# PDF GENERATION HELPER FUNCTIONS
# ============================================================================

class LabReportPDF(FPDF):
    """Custom PDF class for laboratory reports."""
    
    def __init__(self):
        super().__init__()
        self.WIDTH = 210
        self.HEIGHT = 297
    
    def header(self):
        """Add header to PDF."""
        self.set_font("Arial", "B", 20)
        self.cell(0, 10, "REFERRAL ASSAY LABORATORY (RAL)", 0, 1, "C")
        self.set_font("Arial", "I", 10)
        self.cell(0, 5, "Laboratory Information Management System (LIMS)", 0, 1, "C")
        self.cell(0, 5, "Professional Laboratory Report", 0, 1, "C")
        self.ln(5)
    
    def footer(self):
        """Add footer to PDF."""
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}", 0, 0, "C")
    
    def add_section_title(self, title: str):
        """Add section title."""
        self.set_font("Arial", "B", 12)
        self.cell(0, 8, title, 0, 1, "L")
        self.ln(2)
    
    def add_info_row(self, label: str, value: str):
        """Add information row."""
        self.set_font("Arial", "", 10)
        self.cell(60, 6, label, 0, 0, "L")
        self.set_font("Arial", "B", 10)
        self.cell(0, 6, str(value), 0, 1, "L")
    
    def add_table(self, headers: List[str], data: List[List[str]]):
        """Add table to PDF."""
        self.set_font("Arial", "B", 9)
        col_width = self.WIDTH / len(headers)
        
        # Header
        for header in headers:
            self.cell(col_width, 8, header, 1, 0, "C")
        self.ln()
        
        # Data rows
        self.set_font("Arial", "", 8)
        for row in data:
            for i, cell in enumerate(row):
                self.cell(col_width, 8, str(cell)[:20], 1, 0, "L")
            self.ln()

def generate_lab_report_pdf(sample_id: str, results_df: pd.DataFrame) -> bytes:
    """Generate a professional laboratory report PDF."""
    try:
        pdf = LabReportPDF()
        pdf.add_page()
        
        # Sample Information Section
        pdf.add_section_title("SAMPLE INFORMATION")
        pdf.add_info_row("Sample ID:", sample_id)
        pdf.add_info_row("Report Date:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        pdf.add_info_row("Laboratory:", "Referral Assay Laboratory (RAL)")
        pdf.ln(3)
        
        # Test Results Section
        pdf.add_section_title("TEST RESULTS")
        
        if len(results_df) > 0:
            headers = ["Test Name", "Observed", "Limits", "Conformity"]
            data = []
            
            for _, row in results_df.iterrows():
                data.append([
                    str(row.get("Test_Name", ""))[:20],
                    str(row.get("Result_Value", ""))[:15],
                    str(row.get("Limits", ""))[:15],
                    str(row.get("Conformity", ""))[:15]
                ])
            
            pdf.add_table(headers, data)
        else:
            pdf.set_font("Arial", "I", 10)
            pdf.cell(0, 8, "No test results available", 0, 1, "L")
        
        pdf.ln(5)
        
        # Signature Section
        pdf.add_section_title("CERTIFICATION")
        pdf.set_font("Arial", "", 9)
        pdf.multi_cell(0, 5, 
            "This report certifies that the above mentioned samples have been tested "
            "in accordance with the Indian Standards (IS) codes and the results are "
            "accurate to the best of our knowledge and equipment capabilities.")
        pdf.ln(10)
        pdf.cell(0, 6, "_____________________", 0, 1, "L")
        pdf.cell(0, 6, "Authorized Signature", 0, 1, "L")
        
        # Return PDF as bytes
        return pdf.output(dest='S').encode('latin-1')
    except Exception as e:
        st.error(f"Error generating PDF: {str(e)}")
        return b""

# ============================================================================
# PAGE 1: NEW INTAKE (OCR / SCRAPING ENGINE)
# ============================================================================

def page_new_intake():
    """Page for uploading and processing new test requests."""
    st.title("🧪 New Intake - OCR Processing")
    st.markdown("Upload a PDF test request to extract Sample ID and IS Code")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("Upload Test Request")
        pdf_file = st.file_uploader(
            "Upload PDF Test Request",
            type=["pdf"],
            help="Upload a laboratory test request PDF"
        )
    
    with col2:
        st.subheader("Extraction Status")
        if pdf_file is not None:
            st.info(f"File uploaded: {pdf_file.name}")
    
    if pdf_file is not None:
        with st.spinner("Processing PDF with Gemini AI..."):
            extracted_data = extract_data_from_pdf(pdf_file)
        
        if extracted_data:
            st.success("Data extraction completed!")
            
            # Display extracted data for confirmation
            st.subheader("Extracted Information")
            
            col1, col2 = st.columns(2)
            
            with col1:
                sample_id = st.text_input(
                    "Sample ID",
                    value=extracted_data.get("sample_id", ""),
                    help="Unique identifier for the sample"
                )
            
            with col2:
                is_code = st.text_input(
                    "IS Code",
                    value=extracted_data.get("is_code", ""),
                    help="Indian Standard code (e.g., IS 5405)"
                )
            
            with st.expander("View Raw OCR Text"):
                st.text_area(
                    "Raw OCR Output",
                    value=extracted_data.get("raw_ocr_text", ""),
                    height=200,
                    disabled=True
                )
            
            # Confirmation and submission
            st.subheader("Confirm and Submit")
            
            col1, col2, col3 = st.columns([1, 1, 1])
            
            with col2:
                if st.button("Submit to Database", use_container_width=True):
                    if not sample_id or not is_code:
                        st.error("Please provide both Sample ID and IS Code")
                    else:
                        # Prepare data for submission
                        submission_data = [
                            sample_id,
                            is_code,
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            extracted_data.get("raw_ocr_text", "")
                        ]
                        
                        # Append to Google Sheet
                        if append_to_sheet("RAL_LIMS", "Samples", submission_data):
                            st.success(f"✅ Sample {sample_id} successfully added to database!")
                            st.balloons()
                            
                            # Log the submission
                            st.session_state.last_submitted_sample = sample_id
                        else:
                            st.error("Failed to submit sample to database")
            
            # Display last submitted sample
            if "last_submitted_sample" in st.session_state:
                st.info(f"Last submitted: {st.session_state.last_submitted_sample}")

# ============================================================================
# PAGE 2: LAB FLOOR (MOBILE TESTING UI)
# ============================================================================

def page_lab_floor():
    """Page for laboratory testing on the lab floor."""
    st.title("🔬 Lab Floor - Testing Interface")
    st.markdown("Select a sample and record test results with evidence")
    
    # Fetch pending samples from Google Sheet
    samples_df = get_sheet_data("RAL_LIMS", "Samples")
    
    if len(samples_df) == 0:
        st.warning("No samples found in database. Please add samples via New Intake page.")
        return
    
    # Sample selection
    st.subheader("Select Sample")
    sample_ids = samples_df["Sample_ID"].tolist()
    selected_sample = st.selectbox(
        "Available Samples",
        options=sample_ids,
        help="Select a sample to test"
    )
    
    if selected_sample:
        # Get sample details
        sample_row = samples_df[samples_df["Sample_ID"] == selected_sample].iloc[0]
        is_code = sample_row.get("IS_Code", "")
        
        st.info(f"Selected Sample: **{selected_sample}** | IS Code: **{is_code}**")
        
        # Fetch test parameters for this IS code
        params_df = get_sheet_data("RAL_LIMS", "IS_Parameters")
        
        if len(params_df) == 0:
            st.error("No test parameters found in database.")
            return
        
        # Filter parameters by IS code
        relevant_params = params_df[params_df["IS_Code"] == is_code]
        
        if len(relevant_params) == 0:
            st.warning(f"No test parameters found for IS Code: {is_code}")
            return
        
        st.subheader(f"Tests for {is_code} ({len(relevant_params)} parameters)")
        
        # Create a form for each test parameter
        with st.form(key="test_form", clear_on_submit=True):
            test_results = []
            
            for idx, (_, param_row) in enumerate(relevant_params.iterrows()):
                test_name = param_row.get("Test_Name", "")
                parameter_id = param_row.get("Parameter_ID", "")
                limits = param_row.get("Limits", "")
                
                st.markdown(f"### Test {idx + 1}: {test_name}")
                
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.text(f"Limits: {limits}")
                    observed_result = st.text_input(
                        "Observed Result",
                        key=f"result_{idx}",
                        placeholder="Enter measured value"
                    )
                
                with col2:
                    conformity = st.radio(
                        "Conformity",
                        options=["Conforms", "Does Not Conform", "N/A"],
                        key=f"conformity_{idx}",
                        horizontal=True
                    )
                
                # Camera input for evidence
                evidence_photo = st.camera_input(
                    f"Capture Evidence - {test_name}",
                    key=f"photo_{idx}"
                )
                
                test_results.append({
                    "parameter_id": parameter_id,
                    "test_name": test_name,
                    "observed_result": observed_result,
                    "conformity": conformity,
                    "evidence_photo": evidence_photo
                })
                
                st.divider()
            
            # Submit button
            submit_button = st.form_submit_button(
                "Submit Test Results",
                use_container_width=True
            )
            
            if submit_button:
                with st.spinner("Processing and uploading test results..."):
                    all_valid = True
                    
                    for result in test_results:
                        if not result["observed_result"]:
                            st.error(f"Please enter result for {result['test_name']}")
                            all_valid = False
                    
                    if not all_valid:
                        st.error("Please fill in all required fields")
                    else:
                        # Process and save results
                        success_count = 0
                        
                        for result in test_results:
                            image_url = None
                            
                            # Upload evidence photo to Google Drive if captured
                            if result["evidence_photo"] is not None:
                                image_data = io.BytesIO()
                                Image.open(result["evidence_photo"]).save(image_data, format='JPEG')
                                image_data.seek(0)
                                
                                # Use a default folder ID (configure this in secrets)
                                try:
                                    folder_id = st.secrets.get("google_drive", {}).get("folder_id", "root")
                                    image_url = upload_image_to_drive(image_data, folder_id)
                                except:
                                    image_url = "upload_pending"
                            
                            # Prepare result row for Google Sheet
                            result_row = [
                                f"RES_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                                selected_sample,
                                result["parameter_id"],
                                result["observed_result"],
                                result["conformity"],
                                image_url or "No image"
                            ]
                            
                            # Append to Test_Results sheet
                            if append_to_sheet("RAL_LIMS", "Test_Results", result_row):
                                success_count += 1
                        
                        if success_count == len(test_results):
                            st.success(f"✅ All {success_count} test results submitted successfully!")
                            st.balloons()
                        else:
                            st.warning(f"Submitted {success_count}/{len(test_results)} results. Check errors above.")

# ============================================================================
# PAGE 3: REPORTS (PDF GENERATION)
# ============================================================================

def page_reports():
    """Page for generating and downloading laboratory reports."""
    st.title("📊 Reports - PDF Generation")
    st.markdown("Generate professional laboratory reports for completed samples")
    
    # Fetch completed samples
    results_df = get_sheet_data("RAL_LIMS", "Test_Results")
    samples_df = get_sheet_data("RAL_LIMS", "Samples")
    params_df = get_sheet_data("RAL_LIMS", "IS_Parameters")
    
    if len(results_df) == 0:
        st.warning("No test results found. Please complete tests via Lab Floor page.")
        return
    
    # Get unique sample IDs from results
    sample_ids_with_results = results_df["Sample_ID"].unique().tolist()
    
    # Sample selection
    st.subheader("Select Sample for Report")
    selected_sample = st.selectbox(
        "Completed Samples",
        options=sample_ids_with_results,
        help="Select a sample with completed tests"
    )
    
    if selected_sample:
        # Get sample details
        sample_details = samples_df[samples_df["Sample_ID"] == selected_sample]
        
        if len(sample_details) > 0:
            sample_info = sample_details.iloc[0]
            st.info(f"Sample: {selected_sample} | IS Code: {sample_info.get('IS_Code', 'N/A')}")
        
        # Get test results for this sample
        sample_results = results_df[results_df["Sample_ID"] == selected_sample].copy()
        
        # Join with parameters to get test names and limits
        sample_results = sample_results.merge(
            params_df,
            left_on="Parameter_ID",
            right_on="Parameter_ID",
            how="left"
        )
        
        st.subheader("Test Results Summary")
        
        # Display results in table
        display_cols = ["Test_Name", "Result_Value", "Limits", "Conformity", "Image_Drive_Link"]
        available_cols = [col for col in display_cols if col in sample_results.columns]
        
        if available_cols:
            st.dataframe(
                sample_results[available_cols],
                use_container_width=True,
                hide_index=True
            )
        
        # Report generation section
        st.subheader("Generate Official Report")
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            report_title = st.text_input(
                "Report Title",
                value=f"Laboratory Report - {selected_sample}",
                help="Custom title for the report"
            )
        
        with col2:
            include_images = st.checkbox("Include Image Links in Report", value=True)
        
        # Generate button
        if st.button("Generate Official Report", use_container_width=True):
            with st.spinner("Generating PDF report..."):
                pdf_bytes = generate_lab_report_pdf(selected_sample, sample_results)
                
                if pdf_bytes:
                    st.success("✅ Report generated successfully!")
                    
                    # Download button
                    st.download_button(
                        label="📥 Download PDF Report",
                        data=pdf_bytes,
                        file_name=f"RAL_Report_{selected_sample}_{datetime.now().strftime('%Y%m%d')}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
                    
                    # Display preview
                    with st.expander("Preview Report"):
                        st.info("PDF preview not available in browser. Please download to view.")
                else:
                    st.error("Failed to generate report. Check the data and try again.")
        
        # Additional report options
        st.subheader("Report Management")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("View Raw Data", use_container_width=True):
                with st.expander("Raw Test Data"):
                    st.dataframe(sample_results, use_container_width=True)
        
        with col2:
            if st.button("Export as CSV", use_container_width=True):
                csv_data = sample_results.to_csv(index=False)
                st.download_button(
                    label="📊 Download CSV",
                    data=csv_data,
                    file_name=f"RAL_Data_{selected_sample}_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )

# ============================================================================
# MAIN APP ROUTING
# ============================================================================

def main():
    """Main application entry point."""
    
    # Sidebar navigation
    st.sidebar.title("🧪 RAL LIMS")
    st.sidebar.markdown("---")
    
    page = st.sidebar.radio(
        "Navigation",
        options=["New Intake", "Lab Floor", "Reports"],
        icons=["📥", "🔬", "📊"]
    )
    
    st.sidebar.markdown("---")
    
    # Sidebar information
    st.sidebar.subheader("System Information")
    st.sidebar.text("Status: Online")
    st.sidebar.text(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    # Quick stats
    with st.sidebar.expander("Database Stats"):
        try:
            samples_df = get_sheet_data("RAL_LIMS", "Samples")
            results_df = get_sheet_data("RAL_LIMS", "Test_Results")
            
            st.metric("Total Samples", len(samples_df))
            st.metric("Test Results", len(results_df))
        except:
            st.warning("Unable to fetch database stats")
    
    st.sidebar.markdown("---")
    st.sidebar.caption("Referral Assay Laboratory LIMS v1.0")
    
    # Route to selected page
    if page == "New Intake":
        page_new_intake()
    elif page == "Lab Floor":
        page_lab_floor()
    elif page == "Reports":
        page_reports()

if __name__ == "__main__":
    main()
