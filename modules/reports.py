from pathlib import Path
from reportlab.platypus import Image as RLImage

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
CHUSBC_LOGO = ASSETS_DIR / "CHUSBC.jpg"

# Inside build_certified_pdf():
logo_left = None
if CHUSBC_LOGO.is_file():
    logo_left = RLImage(str(CHUSBC_LOGO), width=52, height=52)

# Check for host center logo
center_info = CENTERS.get(host_code, {})
center_logo_name = center_info.get("logo_file")
logo_right = None
if center_logo_name and (ASSETS_DIR / center_logo_name).is_file():
    logo_right = RLImage(str(ASSETS_DIR / center_logo_name), width=52, height=52)

header_table_data = [
    [
        logo_left or "",
        [
            Paragraph("CECIL HARFORD UNITED STATES BOWLING CONGRESS", assoc_style),
            Paragraph(escape(tourney_name).upper(), title_style),
            Paragraph(f"<b>Official Certified Standing Sheet</b> &nbsp;|&nbsp; {escape(center_name)}", meta_style),
        ],
        logo_right or "",
    ]
]
t_header = Table(header_table_data, colWidths=[65, 410, 65])
t_header.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("ALIGN", (0, 0), (0, 0), "LEFT"),
    ("ALIGN", (1, 0), (1, 0), "CENTER"),
    ("ALIGN", (2, 0), (2, 0), "RIGHT"),
]))
story.append(t_header)