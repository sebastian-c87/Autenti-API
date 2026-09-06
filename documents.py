"""Generowanie testowego PDF z obsługą polskich znaków."""
from io import BytesIO  # PDF powstaje w pamięci.
from pathlib import Path  # Ścieżka do dołączonego fontu.
from xml.sax.saxutils import escape  # Dane nie mogą wstrzykiwać znaczników PDF.
from reportlab.pdfbase import pdfmetrics  # Rejestr fontów.
from reportlab.pdfbase.ttfonts import TTFont  # Font Unicode.
from reportlab.lib.styles import ParagraphStyle  # Czytelne akapity.
from reportlab.lib.colors import HexColor  # Kolory dokumentu.
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer  # Automatyczny podział stron.
from reportlab.lib.pagesizes import A4  # Format dokumentu.

pdfmetrics.registerFont(TTFont("CRM", str(Path(__file__).parent / "assets" / "DejaVuSans.ttf")))  # Ten sam font na Macu i Linuxie.

def make_pdf(data):  # Szablon techniczny; nie jest gotową umową prawną.
    buffer = BytesIO()  # Bufor wyniku.
    style = ParagraphStyle("body", fontName="CRM", fontSize=10, leading=16, spaceAfter=9)  # Treść.
    heading = ParagraphStyle("heading", parent=style, fontSize=19, leading=26, textColor=HexColor("#143d59"), spaceAfter=18)  # Tytuł.
    story = [Paragraph("DOKUMENT TESTOWY - NIE ZAWIERAĆ NA JEGO PODSTAWIE UMOWY", style), Paragraph(escape(data["title"]), heading)]  # Jawny charakter prototypu.
    story.append(Paragraph("Prototyp przepływu umowy rezerwacyjnej lokalu. Ten dokument służy wyłącznie do sprawdzenia integracji i podpisów.", style))  # Bez niepełnych klauzul prawnych.
    for i, person in enumerate(data["clients"], 1):  # Jeden akapit dla każdego klienta.
        text = f"Klient {i}: {person['firstName']} {person['lastName']} | E-mail: {person['email']} | Adres: {person.get('address', '')}"  # Dane z formularza.
        story.append(Paragraph(escape(text), style))  # Bezpieczny tekst.
    developer = data.get("developer")  # Reprezentant może być pominięty w teście.
    if developer:  # Wariant dwustronny.
        story.append(Paragraph(escape(f"Deweloper: {developer.get('company', '')}. Reprezentant: {developer['firstName']} {developer['lastName']}. E-mail: {developer['email']}"), style))  # Firma i osoba oddzielnie.
    else: story.append(Paragraph("Deweloper pominięty - test podpisania wyłącznie przez klienta/klientów.", style))  # Nie sugeruj pełnej umowy.
    story.append(Spacer(1, 14))  # Odstęp.
    story.append(Paragraph(escape("Lokal / inwestycja: " + data.get("property", "")), style))  # Dane lokalu.
    for line in data.get("terms", "").splitlines():  # Edytowalne warunki demonstracyjne.
        story.append(Paragraph(escape(line) or " ", style))  # Obsługa długiej treści i nowych stron.
    story.append(Spacer(1, 18))  # Oddzielenie stopki.
    story.append(Paragraph("Docelowo zastąp ten szablon zatwierdzoną treścią umowy dewelopera. Podpisy elektroniczne zostaną dodane przez Autenti.", style))  # Nie rysuj fikcyjnych podpisów.
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=50, leftMargin=50, topMargin=45, bottomMargin=45)  # Marginesy.
    doc.build(story)  # Automatyczne łamanie stron.
    return buffer.getvalue()  # Gotowy PDF.
