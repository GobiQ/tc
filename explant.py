import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date
import os
import json
import plotly.express as px
import plotly.graph_objects as go
import qrcode
from io import BytesIO
import base64
import uuid
from reportlab.lib.pagesizes import letter, LETTER
from reportlab.lib.units import inch, mm
try:
    from barcode import Code128
    from barcode.writer import ImageWriter
    BARCODE_AVAILABLE = True
except ImportError:
    BARCODE_AVAILABLE = False
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle

# Database setup
DB_PATH = "tissue_culture.db"

def init_db():
    """Initialize the database with all required tables."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Orders table
    c.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_name TEXT NOT NULL,
            cultivar TEXT NOT NULL,
            num_plants INTEGER NOT NULL,
            plant_size TEXT NOT NULL,
            order_date DATE NOT NULL,
            delivery_quantity INTEGER,
            is_recurring INTEGER DEFAULT 0,
            completed INTEGER DEFAULT 0,
            completion_date DATE,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Add new columns if they don't exist (for existing databases)
    c.execute("PRAGMA table_info(orders)")
    columns = [column[1] for column in c.fetchall()]
    if 'completed' not in columns:
        c.execute("ALTER TABLE orders ADD COLUMN completed INTEGER DEFAULT 0")
    if 'completion_date' not in columns:
        c.execute("ALTER TABLE orders ADD COLUMN completion_date DATE")
    if 'delivery_quantity' not in columns:
        c.execute("ALTER TABLE orders ADD COLUMN delivery_quantity INTEGER")
    if 'is_recurring' not in columns:
        c.execute("ALTER TABLE orders ADD COLUMN is_recurring INTEGER DEFAULT 0")
    
    # Explant batches table (initiation)
    c.execute('''
        CREATE TABLE IF NOT EXISTS explant_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            batch_name TEXT NOT NULL,
            num_explants INTEGER NOT NULL,
            explant_type TEXT NOT NULL,
            media_type TEXT NOT NULL,
            hormones TEXT,
            additional_elements TEXT,
            initiation_date DATE NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    ''')
    
    # Add new columns if they don't exist (for existing databases)
    c.execute("PRAGMA table_info(explant_batches)")
    columns = [column[1] for column in c.fetchall()]
    if 'hormones' not in columns:
        c.execute("ALTER TABLE explant_batches ADD COLUMN hormones TEXT")
    if 'additional_elements' not in columns:
        c.execute("ALTER TABLE explant_batches ADD COLUMN additional_elements TEXT")
    if 'pathogen_status' not in columns:
        c.execute("ALTER TABLE explant_batches ADD COLUMN pathogen_status TEXT")
    
    # Infection records table
    c.execute('''
        CREATE TABLE IF NOT EXISTS infection_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            num_infected INTEGER NOT NULL,
            infection_type TEXT NOT NULL,
            identification_date DATE NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (batch_id) REFERENCES explant_batches(id)
        )
    ''')
    
    # Add new columns if they don't exist (for existing databases)
    c.execute("PRAGMA table_info(infection_records)")
    columns = [column[1] for column in c.fetchall()]
    if 'num_lost' not in columns:
        c.execute("ALTER TABLE infection_records ADD COLUMN num_lost INTEGER DEFAULT 0")
    if 'num_affected' not in columns:
        c.execute("ALTER TABLE infection_records ADD COLUMN num_affected INTEGER DEFAULT 0")
    
    # Transfer records table
    c.execute('''
        CREATE TABLE IF NOT EXISTS transfer_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            parent_transfer_id INTEGER,
            transfer_date DATE NOT NULL,
            explants_in INTEGER NOT NULL,
            explants_out INTEGER NOT NULL,
            new_media TEXT NOT NULL,
            hormones TEXT,
            additional_elements TEXT,
            multiplication_occurred INTEGER NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (batch_id) REFERENCES explant_batches(id),
            FOREIGN KEY (parent_transfer_id) REFERENCES transfer_records(id)
        )
    ''')
    
    # Add new columns if they don't exist (for existing databases)
    c.execute("PRAGMA table_info(transfer_records)")
    columns = [column[1] for column in c.fetchall()]
    if 'hormones' not in columns:
        c.execute("ALTER TABLE transfer_records ADD COLUMN hormones TEXT")
    if 'additional_elements' not in columns:
        c.execute("ALTER TABLE transfer_records ADD COLUMN additional_elements TEXT")
    
    # Rooting records table
    c.execute('''
        CREATE TABLE IF NOT EXISTS rooting_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transfer_id INTEGER,
            batch_id INTEGER NOT NULL,
            num_placed INTEGER NOT NULL,
            placement_date DATE NOT NULL,
            num_rooted INTEGER,
            rooting_date DATE,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (transfer_id) REFERENCES transfer_records(id),
            FOREIGN KEY (batch_id) REFERENCES explant_batches(id)
        )
    ''')
    
    # Delivery records table
    c.execute('''
        CREATE TABLE IF NOT EXISTS delivery_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            batch_id INTEGER,
            num_delivered INTEGER NOT NULL,
            delivery_date DATE NOT NULL,
            delivery_method TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (batch_id) REFERENCES explant_batches(id)
        )
    ''')
    
    # Labels table for QR code label tracking
    c.execute('''
        CREATE TABLE IF NOT EXISTS labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            label_uuid TEXT UNIQUE NOT NULL,
            client_name TEXT NOT NULL,
            cultivar TEXT NOT NULL,
            order_date DATE NOT NULL,
            initiation_date DATE NOT NULL,
            stages TEXT NOT NULL,
            pathogen_status TEXT,
            num_labels INTEGER DEFAULT 1,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    ''')
    
    conn.commit()
    conn.close()

def get_connection():
    """Get database connection."""
    return sqlite3.connect(DB_PATH)

# Helper functions for database operations
def add_order(client_name, cultivar, num_plants, plant_size, order_date, delivery_quantity, is_recurring, notes):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO orders (client_name, cultivar, num_plants, plant_size, order_date, delivery_quantity, is_recurring, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (client_name, cultivar, num_plants, plant_size, str(order_date), delivery_quantity, 1 if is_recurring else 0, notes))
    conn.commit()
    order_id = c.lastrowid
    conn.close()
    return order_id

def get_orders():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM orders ORDER BY order_date DESC", conn)
    conn.close()
    return df

def update_order(order_id, client_name, cultivar, num_plants, plant_size, order_date, delivery_quantity, is_recurring, notes):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE orders 
        SET client_name = ?, cultivar = ?, num_plants = ?, plant_size = ?, order_date = ?, delivery_quantity = ?, is_recurring = ?, notes = ?
        WHERE id = ?
    ''', (client_name, cultivar, num_plants, plant_size, str(order_date), delivery_quantity, 1 if is_recurring else 0, notes, order_id))
    conn.commit()
    conn.close()

def delete_order(order_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()

def add_explant_batch(order_id, batch_name, num_explants, explant_type, media_type, hormones, additional_elements, initiation_date, notes, pathogen_status=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO explant_batches (order_id, batch_name, num_explants, explant_type, media_type, hormones, additional_elements, initiation_date, notes, pathogen_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (order_id, batch_name, num_explants, explant_type, media_type, hormones, additional_elements, initiation_date, notes, pathogen_status))
    conn.commit()
    batch_id = c.lastrowid
    conn.close()
    return batch_id

def get_explant_batches(order_id=None):
    conn = get_connection()
    if order_id:
        df = pd.read_sql_query(
            "SELECT * FROM explant_batches WHERE order_id = ? ORDER BY initiation_date DESC",
            conn, params=(order_id,)
        )
    else:
        df = pd.read_sql_query("SELECT * FROM explant_batches ORDER BY initiation_date DESC", conn)
    conn.close()
    return df

def update_explant_batch(batch_id, order_id, batch_name, num_explants, explant_type, media_type, hormones, additional_elements, initiation_date, notes, pathogen_status=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE explant_batches 
        SET order_id = ?, batch_name = ?, num_explants = ?, explant_type = ?, media_type = ?, 
            hormones = ?, additional_elements = ?, initiation_date = ?, notes = ?, pathogen_status = ?
        WHERE id = ?
    ''', (order_id, batch_name, num_explants, explant_type, media_type, hormones, additional_elements, initiation_date, notes, pathogen_status, batch_id))
    conn.commit()
    conn.close()

def delete_explant_batch(batch_id):
    conn = get_connection()
    c = conn.cursor()
    # Delete related records first (cascading)
    c.execute("DELETE FROM infection_records WHERE batch_id = ?", (batch_id,))
    c.execute("DELETE FROM transfer_records WHERE batch_id = ?", (batch_id,))
    c.execute("DELETE FROM rooting_records WHERE batch_id = ?", (batch_id,))
    c.execute("DELETE FROM explant_batches WHERE id = ?", (batch_id,))
    conn.commit()
    conn.close()

def add_infection_record(batch_id, num_lost, num_affected, infection_type, identification_date, notes):
    conn = get_connection()
    c = conn.cursor()
    # Keep num_infected for backward compatibility (sum of lost and affected)
    num_infected = num_lost + num_affected
    c.execute('''
        INSERT INTO infection_records (batch_id, num_infected, num_lost, num_affected, infection_type, identification_date, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (batch_id, num_infected, num_lost, num_affected, infection_type, identification_date, notes))
    conn.commit()
    record_id = c.lastrowid
    conn.close()
    return record_id

def get_infection_records(batch_id=None):
    conn = get_connection()
    if batch_id:
        df = pd.read_sql_query(
            "SELECT * FROM infection_records WHERE batch_id = ? ORDER BY identification_date DESC",
            conn, params=(batch_id,)
        )
    else:
        df = pd.read_sql_query("SELECT * FROM infection_records ORDER BY identification_date DESC", conn)
    conn.close()
    return df

def get_total_infections_for_batch(batch_id):
    """Get total number of explants lost to contamination (for calculating remaining healthy)."""
    conn = get_connection()
    c = conn.cursor()
    # Use num_lost if available, otherwise fall back to num_infected for backward compatibility
    c.execute("SELECT COALESCE(SUM(COALESCE(num_lost, num_infected)), 0) FROM infection_records WHERE batch_id = ?", (batch_id,))
    total = c.fetchone()[0]
    conn.close()
    return total

def update_infection_record(record_id, batch_id, num_lost, num_affected, infection_type, identification_date, notes):
    conn = get_connection()
    c = conn.cursor()
    # Keep num_infected for backward compatibility (sum of lost and affected)
    num_infected = num_lost + num_affected
    c.execute('''
        UPDATE infection_records 
        SET batch_id = ?, num_infected = ?, num_lost = ?, num_affected = ?, infection_type = ?, identification_date = ?, notes = ?
        WHERE id = ?
    ''', (batch_id, num_infected, num_lost, num_affected, infection_type, identification_date, notes, record_id))
    conn.commit()
    conn.close()

def delete_infection_record(record_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM infection_records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()

def add_transfer_record(batch_id, parent_transfer_id, transfer_date, explants_in, explants_out, new_media, hormones, additional_elements, multiplication_occurred, notes):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO transfer_records (batch_id, parent_transfer_id, transfer_date, explants_in, explants_out, new_media, hormones, additional_elements, multiplication_occurred, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (batch_id, parent_transfer_id, transfer_date, explants_in, explants_out, new_media, hormones, additional_elements, multiplication_occurred, notes))
    conn.commit()
    transfer_id = c.lastrowid
    conn.close()
    return transfer_id

def get_transfer_records(batch_id=None):
    conn = get_connection()
    if batch_id:
        df = pd.read_sql_query(
            "SELECT * FROM transfer_records WHERE batch_id = ? ORDER BY transfer_date DESC",
            conn, params=(batch_id,)
        )
    else:
        df = pd.read_sql_query("SELECT * FROM transfer_records ORDER BY transfer_date DESC", conn)
    conn.close()
    return df

def update_transfer_record(transfer_id, batch_id, parent_transfer_id, transfer_date, explants_in, explants_out, new_media, hormones, additional_elements, multiplication_occurred, notes):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE transfer_records 
        SET batch_id = ?, parent_transfer_id = ?, transfer_date = ?, explants_in = ?, explants_out = ?, 
            new_media = ?, hormones = ?, additional_elements = ?, multiplication_occurred = ?, notes = ?
        WHERE id = ?
    ''', (batch_id, parent_transfer_id, transfer_date, explants_in, explants_out, new_media, hormones, additional_elements, multiplication_occurred, notes, transfer_id))
    conn.commit()
    conn.close()

def delete_transfer_record(transfer_id):
    conn = get_connection()
    c = conn.cursor()
    # Delete related rooting records first
    c.execute("DELETE FROM rooting_records WHERE transfer_id = ?", (transfer_id,))
    c.execute("DELETE FROM transfer_records WHERE id = ?", (transfer_id,))
    conn.commit()
    conn.close()

def add_rooting_record(transfer_id, batch_id, num_placed, placement_date, num_rooted, rooting_date, notes):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO rooting_records (transfer_id, batch_id, num_placed, placement_date, num_rooted, rooting_date, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (transfer_id, batch_id, num_placed, str(placement_date), num_rooted, str(rooting_date) if rooting_date else None, notes))
    conn.commit()
    record_id = c.lastrowid
    conn.close()
    return record_id

def update_rooting_record(record_id, num_rooted, rooting_date):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE rooting_records 
        SET num_rooted = ?, rooting_date = ?
        WHERE id = ?
    ''', (num_rooted, str(rooting_date) if rooting_date else None, record_id))
    conn.commit()
    conn.close()

def update_rooting_record_full(record_id, transfer_id, batch_id, num_placed, placement_date, num_rooted, rooting_date, notes):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE rooting_records 
        SET transfer_id = ?, batch_id = ?, num_placed = ?, placement_date = ?, num_rooted = ?, rooting_date = ?, notes = ?
        WHERE id = ?
    ''', (transfer_id, batch_id, num_placed, str(placement_date), num_rooted, str(rooting_date) if rooting_date else None, notes, record_id))
    conn.commit()
    conn.close()

def delete_rooting_record(record_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM rooting_records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()

def get_rooting_records(batch_id=None, transfer_id=None):
    conn = get_connection()
    if batch_id:
        df = pd.read_sql_query(
            "SELECT * FROM rooting_records WHERE batch_id = ? ORDER BY placement_date DESC",
            conn, params=(batch_id,)
        )
    elif transfer_id:
        df = pd.read_sql_query(
            "SELECT * FROM rooting_records WHERE transfer_id = ? ORDER BY placement_date DESC",
            conn, params=(transfer_id,)
        )
    else:
        df = pd.read_sql_query("SELECT * FROM rooting_records ORDER BY placement_date DESC", conn)
    conn.close()
    return df

def add_delivery_record(order_id, batch_id, num_delivered, delivery_date, delivery_method, notes):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO delivery_records (order_id, batch_id, num_delivered, delivery_date, delivery_method, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (order_id, batch_id, num_delivered, str(delivery_date), delivery_method, notes))
    conn.commit()
    record_id = c.lastrowid
    conn.close()
    return record_id

def update_delivery_record(record_id, order_id, batch_id, num_delivered, delivery_date, delivery_method, notes):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE delivery_records 
        SET order_id = ?, batch_id = ?, num_delivered = ?, delivery_date = ?, delivery_method = ?, notes = ?
        WHERE id = ?
    ''', (order_id, batch_id, num_delivered, str(delivery_date), delivery_method, notes, record_id))
    conn.commit()
    conn.close()

def delete_delivery_record(record_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM delivery_records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()

def get_delivery_records(order_id=None, batch_id=None):
    conn = get_connection()
    if order_id:
        df = pd.read_sql_query(
            "SELECT * FROM delivery_records WHERE order_id = ? ORDER BY delivery_date DESC",
            conn, params=(order_id,)
        )
    elif batch_id:
        df = pd.read_sql_query(
            "SELECT * FROM delivery_records WHERE batch_id = ? ORDER BY delivery_date DESC",
            conn, params=(batch_id,)
        )
    else:
        df = pd.read_sql_query("SELECT * FROM delivery_records ORDER BY delivery_date DESC", conn)
    conn.close()
    return df

# Label functions for QR code generation
def add_label(order_id, label_uuid, client_name, cultivar, order_date, initiation_date, stages, pathogen_status, num_labels, notes):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO labels (order_id, label_uuid, client_name, cultivar, order_date, initiation_date, stages, pathogen_status, num_labels, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (order_id, label_uuid, client_name, cultivar, str(order_date), str(initiation_date), stages, pathogen_status, num_labels, notes))
    conn.commit()
    label_id = c.lastrowid
    conn.close()
    return label_id

def get_labels(order_id=None):
    conn = get_connection()
    if order_id:
        df = pd.read_sql_query(
            "SELECT * FROM labels WHERE order_id = ? ORDER BY created_at DESC",
            conn, params=(order_id,)
        )
    else:
        df = pd.read_sql_query("SELECT * FROM labels ORDER BY created_at DESC", conn)
    conn.close()
    return df

def get_label_by_uuid(label_uuid):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM labels WHERE label_uuid = ?", (label_uuid,))
    label = c.fetchone()
    conn.close()
    if label:
        columns = ['id', 'order_id', 'label_uuid', 'client_name', 'cultivar', 'order_date', 
                   'initiation_date', 'stages', 'pathogen_status', 'num_labels', 'notes', 'created_at']
        return dict(zip(columns, label))
    return None

def delete_label(label_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM labels WHERE id = ?", (label_id,))
    conn.commit()
    conn.close()

def get_pathogens_for_order(order_id):
    """Get all unique pathogens from pathogen_status field in batches of an order (excludes contamination records)."""
    conn = get_connection()
    c = conn.cursor()
    
    # Get pathogens from explant_batches pathogen_status field only (not from contamination/infection records)
    c.execute('''
        SELECT DISTINCT pathogen_status 
        FROM explant_batches
        WHERE order_id = ? AND pathogen_status IS NOT NULL AND pathogen_status != ''
    ''', (order_id,))
    pathogens = [row[0] for row in c.fetchall() if row[0]]
    
    conn.close()
    return list(set(pathogens))  # Return unique pathogens

def generate_qr_code(data, size=10):
    """Generate a QR code image from data."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=size,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    return img

def generate_barcode(data, width=2, height=50):
    """Generate a barcode image from data."""
    if not BARCODE_AVAILABLE:
        raise ImportError("barcode library not available. Install with: pip install python-barcode[images]")
    
    # Use UUID or first 20 chars of data for barcode (barcodes have length limits)
    if len(data) > 20:
        # Use UUID from JSON if available, otherwise truncate
        try:
            import json
            data_dict = json.loads(data)
            barcode_data = data_dict.get('uuid', data[:20])
        except:
            barcode_data = data[:20]
    else:
        barcode_data = data
    
    code128 = Code128(barcode_data, writer=ImageWriter())
    buffer = BytesIO()
    code128.write(buffer, options={'module_width': width, 'module_height': height, 'quiet_zone': 2})
    buffer.seek(0)
    
    from PIL import Image
    img = Image.open(buffer)
    return img

def generate_label_pdf(labels_data, label_size=(2, 1), labels_per_row=3, labels_per_col=10):
    """
    Generate a PDF with multiple labels.
    
    labels_data: list of dicts with label information
    label_size: (width, height) in inches
    labels_per_row: number of labels per row
    labels_per_col: number of labels per column
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=LETTER)
    page_width, page_height = LETTER
    
    label_width = label_size[0] * inch
    label_height = label_size[1] * inch
    
    # Calculate margins to center labels on page
    total_labels_width = labels_per_row * label_width
    total_labels_height = labels_per_col * label_height
    left_margin = (page_width - total_labels_width) / 2
    top_margin = (page_height - total_labels_height) / 2
    
    labels_per_page = labels_per_row * labels_per_col
    
    for label_idx, label_data in enumerate(labels_data):
        # Calculate position on current page
        page_label_idx = label_idx % labels_per_page
        row = page_label_idx // labels_per_row
        col = page_label_idx % labels_per_row
        
        # Start new page if needed
        if label_idx > 0 and page_label_idx == 0:
            c.showPage()
        
        # Calculate label position (from top-left)
        x = left_margin + (col * label_width)
        y = page_height - top_margin - ((row + 1) * label_height)
        
        # Draw label border (optional, for debugging)
        # c.rect(x, y, label_width, label_height)
        
        # Generate QR code or barcode based on code_type
        from reportlab.lib.utils import ImageReader
        code_type = label_data.get('code_type', 'QR Code')
        code_width = 0.7 * inch  # Default for QR code
        
        if code_type == "Barcode":
            # For barcode, use UUID directly
            try:
                barcode_img = generate_barcode(label_data['uuid'], width=1, height=40)
                # Save barcode to buffer
                code_buffer = BytesIO()
                barcode_img.save(code_buffer, format='PNG')
                code_buffer.seek(0)
                
                # Draw barcode on the left side of label
                code_width = 1.2 * inch
                code_height = 0.4 * inch
                code_image = ImageReader(code_buffer)
                c.drawImage(code_image, x + 2*mm, y + (label_height - code_height) / 2, 
                            width=code_width, height=code_height)
            except Exception as e:
                # Fallback to QR code if barcode generation fails
                code_type = "QR Code"
                code_width = 0.7 * inch
        
        if code_type == "QR Code":
            # Generate QR code
            qr_data = json.dumps({
                'uuid': label_data['uuid'],
                'client': label_data['client_name'],
                'cultivar': label_data['cultivar'],
                'order_date': label_data['order_date'],
                'init_date': label_data['initiation_date'],
                'stages': label_data['stages'],
                'pathogens': label_data['pathogen_status'],
                'num_explants': label_data.get('num_explants', None)
            })
            qr_img = generate_qr_code(qr_data, size=6)
            
            # Save QR code to buffer
            code_buffer = BytesIO()
            qr_img.save(code_buffer, format='PNG')
            code_buffer.seek(0)
            
            # Draw QR code on the left side of label
            code_size = 0.7 * inch
            code_width = code_size
            code_image = ImageReader(code_buffer)
            c.drawImage(code_image, x + 2*mm, y + (label_height - code_size) / 2, 
                        width=code_size, height=code_size)
        
        # Draw text on the right side
        text_x = x + code_width + 4*mm
        text_width = label_width - code_width - 6*mm
        
        # Font sizes
        line_height = 7
        text_y = y + label_height - 4*mm
        
        # Get include flags (default to True for backward compatibility)
        include_cultivar = label_data.get('include_cultivar', True)
        include_client = label_data.get('include_client', True)
        include_order_date = label_data.get('include_order_date', True)
        include_init_date = label_data.get('include_init_date', True)
        include_stages = label_data.get('include_stages', True)
        include_explants = label_data.get('include_explants', True)
        include_pathogens = label_data.get('include_pathogens', True)
        
        # Cultivar name (bold, first item if included)
        if include_cultivar:
            c.setFont("Helvetica-Bold", 6)
            cultivar = label_data['cultivar'][:25]
            c.drawString(text_x, text_y, cultivar)
            text_y -= line_height
        
        # Client name
        if include_client:
            c.setFont("Helvetica", 5)
            client_name = label_data['client_name'][:20]  # Truncate if too long
            c.drawString(text_x, text_y, f"Client: {client_name}")
            text_y -= line_height
        
        # Order date
        if include_order_date:
            c.setFont("Helvetica", 5)
            c.drawString(text_x, text_y, f"Order: {label_data['order_date']}")
            text_y -= line_height
        
        # Initiation date
        if include_init_date:
            c.setFont("Helvetica", 5)
            c.drawString(text_x, text_y, f"Init: {label_data['initiation_date']}")
            text_y -= line_height
        
        # Stages
        if include_stages:
            c.setFont("Helvetica", 5)
            stages = label_data['stages'][:30]
            c.drawString(text_x, text_y, f"Stage: {stages}")
            text_y -= line_height
        
        # Number of explants
        if include_explants:
            c.setFont("Helvetica", 5)
            num_explants = label_data.get('num_explants', 'N/A')
            c.drawString(text_x, text_y, f"Explants: {num_explants}")
            text_y -= line_height
        
        # Pathogen status
        if include_pathogens:
            c.setFont("Helvetica", 4)
            if label_data['pathogen_status']:
                pathogens = label_data['pathogen_status'][:35]
                c.drawString(text_x, text_y, f"Pathogens: {pathogens}")
            else:
                c.drawString(text_x, text_y, "Pathogens: none")
            text_y -= line_height
    
    c.save()
    buffer.seek(0)
    return buffer

def mark_order_completed(order_id, completion_date):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE orders 
        SET completed = 1, completion_date = ?
        WHERE id = ?
    ''', (str(completion_date), order_id))
    conn.commit()
    conn.close()

def mark_order_incomplete(order_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE orders 
        SET completed = 0, completion_date = NULL
        WHERE id = ?
    ''', (order_id,))
    conn.commit()
    conn.close()

def get_batch_summary(batch_id):
    """Get a summary of the batch including infections and transfers."""
    conn = get_connection()
    c = conn.cursor()
    
    # Get batch info
    c.execute("SELECT * FROM explant_batches WHERE id = ?", (batch_id,))
    batch = c.fetchone()
    
    if not batch:
        conn.close()
        return None
    
    # Get total infections
    c.execute("SELECT COALESCE(SUM(num_infected), 0) FROM infection_records WHERE batch_id = ?", (batch_id,))
    total_infected = c.fetchone()[0]
    
    # Get latest transfer count
    c.execute("""
        SELECT COALESCE(SUM(explants_out), 0) 
        FROM transfer_records 
        WHERE batch_id = ?
    """, (batch_id,))
    total_transferred = c.fetchone()[0]
    
    conn.close()
    
    return {
        'batch': batch,
        'total_infected': total_infected,
        'total_transferred': total_transferred,
        'healthy': batch[3] - total_infected  # num_explants - total_infected
    }

# Initialize database
init_db()

# Streamlit app
st.set_page_config(
    page_title="Tissue Culture Tracker",
    page_icon=None,
    layout="wide"
)

st.title("Tissue Culture Explant Tracker")

# Sidebar navigation
page = st.sidebar.selectbox(
    "Navigation",
    ["Dashboard", "Order Management", "Explant Initiation", "Contamination Tracking", "Transfer Management", "Rooting Tracking", "Delivery", "Labels", "Timeline", "Statistics", "Archive"]
)

# Dashboard
if page == "Dashboard":
    st.header("Dashboard Overview")
    
    col1, col2, col3, col4 = st.columns(4)
    
    # Get summary statistics
    conn = get_connection()
    
    total_orders = pd.read_sql_query("SELECT COUNT(*) as count FROM orders", conn).iloc[0]['count']
    total_batches = pd.read_sql_query("SELECT COUNT(*) as count FROM explant_batches", conn).iloc[0]['count']
    total_explants = pd.read_sql_query("SELECT COALESCE(SUM(num_explants), 0) as total FROM explant_batches", conn).iloc[0]['total']
    total_infections = pd.read_sql_query("SELECT COALESCE(SUM(num_infected), 0) as total FROM infection_records", conn).iloc[0]['total']
    
    conn.close()
    
    with col1:
        st.metric("Total Orders", total_orders)
    with col2:
        st.metric("Explant Batches", total_batches)
    with col3:
        st.metric("Total Explants", int(total_explants))
    with col4:
        infection_rate = (total_infections / total_explants * 100) if total_explants > 0 else 0
        st.metric("Infection Rate", f"{infection_rate:.1f}%")
    
    st.divider()
    
    # Recent activity
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Recent Orders")
        orders = get_orders()
        if not orders.empty:
            st.dataframe(
                orders[['client_name', 'cultivar', 'num_plants', 'order_date']].head(5),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No orders yet")
    
    with col2:
        st.subheader("Recent Explant Batches")
        batches = get_explant_batches()
        if not batches.empty:
            st.dataframe(
                batches[['batch_name', 'num_explants', 'explant_type', 'initiation_date']].head(5),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No batches yet")

# Order Management
elif page == "Order Management":
    st.header("Order Management")
    
    # Initialize session state for edit mode
    if 'edit_order_id' not in st.session_state:
        st.session_state.edit_order_id = None
    
    tab1, tab2, tab3, tab4 = st.tabs(["Add New Order", "View Orders", "Edit/Delete Orders", "Mark Complete"])
    
    with tab1:
        st.subheader("Add New Order")
        
        with st.form("new_order_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                client_name = st.text_input("Client Name*")
                cultivar = st.text_input("Cultivar*")
                num_plants = st.number_input("Number of Plants*", min_value=1, value=1)
                delivery_quantity = st.number_input("Delivery Quantity (Tissue Culture Plants)*", min_value=0, value=0, help="Number of tissue culture plants the client wants delivered")
            
            with col2:
                plant_size = st.selectbox(
                    "Plant Size*",
                    ["In Vitro Shoots", "Clones", "Teens", "Other"]
                )
                order_date = st.date_input("Order Date*", value=date.today())
                is_recurring = st.checkbox("Recurring Order", value=False, help="Check if this is a recurring delivery order")
                notes = st.text_area("Notes")
            
            submitted = st.form_submit_button("Add Order")
            
            if submitted:
                if client_name and cultivar:
                    order_id = add_order(client_name, cultivar, num_plants, plant_size, str(order_date), delivery_quantity, is_recurring, notes)
                    st.success(f"Order #{order_id} added successfully!")
                else:
                    st.error("Please fill in all required fields")
    
    with tab2:
        st.subheader("All Orders")
        orders = get_orders()
        
        if not orders.empty:
            # Add filter options
            client_filter = st.selectbox(
                "Filter by Client",
                ["All"] + orders['client_name'].unique().tolist()
            )
            
            if client_filter != "All":
                orders = orders[orders['client_name'] == client_filter]
            
            # Format the display to show recurring status
            display_orders = orders.copy()
            if 'is_recurring' in display_orders.columns:
                display_orders['Recurring'] = display_orders['is_recurring'].apply(lambda x: 'Yes' if x == 1 else 'No')
            
            display_cols = ['id', 'client_name', 'cultivar', 'num_plants', 'delivery_quantity', 'Recurring', 'plant_size', 'order_date', 'completed', 'completion_date', 'notes']
            available_cols = [col for col in display_cols if col in display_orders.columns]
            st.dataframe(display_orders[available_cols], use_container_width=True, hide_index=True)
            
            # Export option
            csv = orders.to_csv(index=False)
            st.download_button(
                "Download Orders CSV",
                csv,
                "orders.csv",
                "text/csv"
            )
        else:
            st.info("No orders found")
    
    with tab3:
        st.subheader("Edit or Delete Orders")
        orders = get_orders()
        
        if not orders.empty:
            # Order selection
            order_options = {f"Order #{row['id']} - {row['client_name']} ({row['cultivar']})": row['id'] 
                           for _, row in orders.iterrows()}
            selected_order = st.selectbox("Select Order to Edit/Delete", list(order_options.keys()))
            order_id = order_options[selected_order]
            
            selected_order_data = orders[orders['id'] == order_id].iloc[0]
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Edit Order**")
                with st.form("edit_order_form"):
                    edit_client_name = st.text_input("Client Name*", value=selected_order_data['client_name'])
                    edit_cultivar = st.text_input("Cultivar*", value=selected_order_data['cultivar'])
                    edit_num_plants = st.number_input("Number of Plants*", min_value=1, value=int(selected_order_data['num_plants']))
                    edit_delivery_quantity = st.number_input("Delivery Quantity (Tissue Culture Plants)*", min_value=0, 
                                                              value=int(selected_order_data.get('delivery_quantity', 0)) if pd.notna(selected_order_data.get('delivery_quantity')) else 0,
                                                              help="Number of tissue culture plants the client wants delivered")
                    edit_plant_size = st.selectbox(
                        "Plant Size*",
                        ["In Vitro Shoots", "Clones", "Teens", "Other"],
                        index=["In Vitro Shoots", "Clones", "Teens", "Other"].index(selected_order_data['plant_size']) if selected_order_data['plant_size'] in ["In Vitro Shoots", "Clones", "Teens", "Other"] else 0
                    )
                    edit_order_date = st.date_input("Order Date*", value=pd.to_datetime(selected_order_data['order_date']).date())
                    edit_is_recurring = st.checkbox("Recurring Order", 
                                                   value=bool(selected_order_data.get('is_recurring', 0)) if pd.notna(selected_order_data.get('is_recurring')) else False,
                                                   help="Check if this is a recurring delivery order")
                    edit_notes = st.text_area("Notes", value=selected_order_data['notes'] if pd.notna(selected_order_data['notes']) else "")
                    
                    edit_submitted = st.form_submit_button("Update Order")
                    
                    if edit_submitted:
                        if edit_client_name and edit_cultivar:
                            update_order(order_id, edit_client_name, edit_cultivar, edit_num_plants, edit_plant_size, str(edit_order_date), edit_delivery_quantity, edit_is_recurring, edit_notes)
                            st.success(f"Order #{order_id} updated successfully!")
                            st.rerun()
                        else:
                            st.error("Please fill in all required fields")
            
            with col2:
                st.write("**Delete Order**")
                st.warning("Deleting an order will NOT delete associated batches. This action cannot be undone.")
                
                if st.button("Delete Order", type="primary", use_container_width=True):
                    delete_order(order_id)
                    st.success(f"Order #{order_id} deleted successfully!")
                    st.rerun()
        else:
            st.info("No orders found")
    
    with tab4:
        st.subheader("Mark Order as Complete")
        orders = get_orders()
        
        # Filter to show only incomplete orders
        incomplete_orders = orders[orders.get('completed', 0) == 0] if 'completed' in orders.columns else orders
        
        if not incomplete_orders.empty:
            order_options = {f"Order #{row['id']} - {row['client_name']} ({row['cultivar']})": row['id'] 
                           for _, row in incomplete_orders.iterrows()}
            selected_order = st.selectbox("Select Order to Mark Complete", list(order_options.keys()))
            order_id = order_options[selected_order]
            
            selected_order_data = orders[orders['id'] == order_id].iloc[0]
            
            with st.form("complete_order_form"):
                st.write(f"**Order Details:**")
                st.write(f"- Client: {selected_order_data['client_name']}")
                st.write(f"- Cultivar: {selected_order_data['cultivar']}")
                st.write(f"- Number of Plants: {selected_order_data['num_plants']}")
                delivery_qty = selected_order_data.get('delivery_quantity', 0) if pd.notna(selected_order_data.get('delivery_quantity')) else 0
                is_recurring_val = bool(selected_order_data.get('is_recurring', 0)) if pd.notna(selected_order_data.get('is_recurring')) else False
                st.write(f"- Delivery Quantity: {delivery_qty} tissue culture plants")
                st.write(f"- Recurring Order: {'Yes' if is_recurring_val else 'No'}")
                
                completion_date = st.date_input("Completion Date*", value=date.today())
                
                submitted = st.form_submit_button("Mark Order as Complete")
                
                if submitted:
                    mark_order_completed(order_id, completion_date)
                    st.success(f"Order #{order_id} marked as complete!")
                    st.rerun()
        else:
            st.info("No incomplete orders found")
        
        # Show completed orders
        st.subheader("Completed Orders")
        completed_orders = orders[orders.get('completed', 0) == 1] if 'completed' in orders.columns else pd.DataFrame()
        
        if not completed_orders.empty:
            # Format the display to show recurring status
            display_orders = completed_orders.copy()
            if 'is_recurring' in display_orders.columns:
                display_orders['Recurring'] = display_orders['is_recurring'].apply(lambda x: 'Yes' if x == 1 else 'No')
            
            display_cols = ['id', 'client_name', 'cultivar', 'num_plants', 'delivery_quantity', 'Recurring', 'plant_size', 'order_date', 'completion_date', 'notes']
            available_cols = [col for col in display_cols if col in display_orders.columns]
            st.dataframe(display_orders[available_cols], use_container_width=True, hide_index=True)
            
            # Option to mark as incomplete
            st.subheader("Mark Order as Incomplete")
            completed_order_options = {f"Order #{row['id']} - {row['client_name']} ({row['cultivar']})": row['id'] 
                                      for _, row in completed_orders.iterrows()}
            if completed_order_options:
                selected_completed = st.selectbox("Select Completed Order", list(completed_order_options.keys()))
                completed_order_id = completed_order_options[selected_completed]
                
                if st.button("Mark as Incomplete", type="primary"):
                    mark_order_incomplete(completed_order_id)
                    st.success(f"Order #{completed_order_id} marked as incomplete!")
                    st.rerun()
        else:
            st.info("No completed orders found")

# Explant Initiation
elif page == "Explant Initiation":
    st.header("Explant Initiation")
    
    tab1, tab2, tab3 = st.tabs(["Initiate New Batch", "View Batches", "Edit/Delete Batches"])
    
    with tab1:
        st.subheader("Initiate New Explant Batch")
        
        # Get orders for dropdown
        orders = get_orders()
        
        # Pathogen Status (outside form for reactivity - must be before form to capture value on submit)
        st.subheader("Pathogen Status")
        # Check if we need to reset after successful submission
        if st.session_state.get('reset_pathogen_status', False):
            # Clear the reset flag and delete widget states
            st.session_state.reset_pathogen_status = False
            if 'pathogen_positive_checkbox_new_batch' in st.session_state:
                del st.session_state.pathogen_positive_checkbox_new_batch
            if 'pathogen_selectbox_new_batch' in st.session_state:
                del st.session_state.pathogen_selectbox_new_batch
            if 'pathogen_status_value' in st.session_state:
                del st.session_state.pathogen_status_value
        
        # Initialize from session state if exists, otherwise False
        pathogen_positive = st.checkbox(
            "Pathogen Positive", 
            value=st.session_state.get('pathogen_positive_checkbox_new_batch', False), 
            key="pathogen_positive_checkbox_new_batch"
        )
        
        pathogen_options = [
            "Hop Latent Viroid",
            "Arabis Mosaic Virus",
            "Beet Curly Top Virus",
            "Lettuce Chlorosis Virus",
            "Cannabis Cryptic Virus",
            "Tomato Ringspot Virus",
            "Tobacco Mosaic Virus",
            "Tomato Mosaic Virus",
            "Botrytis cineria",
            "Pythium myriotylum",
            "Fusarium oxysporum",
            "Fusarium solani",
            "Golovinomyces ambrosiae"
        ]
        
        # Get current value from session state if exists
        current_pathogen = st.session_state.get('pathogen_status_value', "Select...")
        if current_pathogen and current_pathogen != "Select..." and current_pathogen in pathogen_options:
            default_index = ["Select..."] + pathogen_options
            try:
                default_idx = default_index.index(current_pathogen)
            except:
                default_idx = 0
        else:
            default_idx = 0
        
        pathogen_status = st.selectbox(
            "Select Pathogen", 
            ["Select..."] + pathogen_options, 
            key="pathogen_selectbox_new_batch",
            disabled=not pathogen_positive,
            index=default_idx if pathogen_positive and default_idx > 0 else 0
        )
        
        if not pathogen_positive or pathogen_status == "Select...":
            pathogen_status = None
        
        # Store pathogen_status in session state so form can access it
        st.session_state.pathogen_status_value = pathogen_status
        
        st.divider()
        
        with st.form("new_batch_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                if not orders.empty:
                    order_options = {f"Order #{row['id']} - {row['client_name']} ({row['cultivar']})": row['id'] 
                                   for _, row in orders.iterrows()}
                    selected_order = st.selectbox("Link to Order (optional)", ["None"] + list(order_options.keys()))
                    order_id = order_options.get(selected_order) if selected_order != "None" else None
                else:
                    st.info("No orders available")
                    order_id = None
                
                batch_name = st.text_input("Batch Name/ID*")
                num_explants = st.number_input("Number of Explants*", min_value=1, value=1)
            
            with col2:
                explant_type = st.selectbox(
                    "Explant Type*",
                    ["Node", "Microshoot", "Meristem", "Other"]
                )
                media_type = st.selectbox(
                    "Media Type*",
                    ["50% EECN", "100% EECN", "50% MS", "100% MS", "50% DKW", "100% DKW", "Rooting Media"]
                )
                initiation_date = st.date_input("Initiation Date*", value=date.today())
            
            st.subheader("Media Additives")
            col3, col4 = st.columns(2)
            
            with col3:
                hormones = st.text_area("Hormones and Concentrations", placeholder="e.g., BAP 2.0 mg/L, IBA 0.5 mg/L")
            
            with col4:
                additional_elements = st.text_area("Additional Elements and Concentrations", placeholder="e.g., Activated charcoal 0.5 g/L, Sucrose 30 g/L")
            
            notes = st.text_area("Notes")
            
            submitted = st.form_submit_button("Initiate Batch")
            
            if submitted:
                # Get pathogen_status from session state (captured before form)
                pathogen_status_val = st.session_state.get('pathogen_status_value', None)
                if batch_name and media_type:
                    batch_id = add_explant_batch(
                        order_id, batch_name, num_explants, explant_type,
                        media_type, hormones or None, additional_elements or None, str(initiation_date), notes, pathogen_status_val
                    )
                    st.success(f"Batch '{batch_name}' (ID: {batch_id}) initiated successfully!")
                    # Set flag to reset pathogen status on next run
                    st.session_state.reset_pathogen_status = True
                    st.rerun()
                else:
                    st.error("Please fill in all required fields")
    
    with tab2:
        st.subheader("All Explant Batches")
        batches = get_explant_batches()
        
        if not batches.empty:
            # Add filter
            explant_filter = st.selectbox(
                "Filter by Explant Type",
                ["All"] + batches['explant_type'].unique().tolist()
            )
            
            if explant_filter != "All":
                batches = batches[batches['explant_type'] == explant_filter]
            
            st.dataframe(batches, use_container_width=True, hide_index=True)
        else:
            st.info("No batches found")
    
    with tab3:
        st.subheader("Edit or Delete Batches")
        batches = get_explant_batches()
        orders = get_orders()
        
        if not batches.empty:
            # Batch selection
            batch_options = {f"Batch #{row['id']} - {row['batch_name']}": row['id'] 
                           for _, row in batches.iterrows()}
            selected_batch = st.selectbox("Select Batch to Edit/Delete", list(batch_options.keys()))
            batch_id = batch_options[selected_batch]
            
            selected_batch_data = batches[batches['id'] == batch_id].iloc[0]
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Edit Batch**")
                with st.form("edit_batch_form"):
                    # Order selection
                    if not orders.empty:
                        order_options = {f"Order #{row['id']} - {row['client_name']} ({row['cultivar']})": row['id'] 
                                       for _, row in orders.iterrows()}
                        current_order_id = selected_batch_data.get('order_id')
                        if pd.notna(current_order_id):
                            current_order = orders[orders['id'] == int(current_order_id)]
                            if not current_order.empty:
                                current_order_key = f"Order #{current_order.iloc[0]['id']} - {current_order.iloc[0]['client_name']} ({current_order.iloc[0]['cultivar']})"
                                default_order = current_order_key if current_order_key in order_options else "None"
                            else:
                                default_order = "None"
                        else:
                            default_order = "None"
                        selected_order = st.selectbox("Link to Order (optional)", ["None"] + list(order_options.keys()), 
                                                     index=(["None"] + list(order_options.keys())).index(default_order) if default_order in (["None"] + list(order_options.keys())) else 0)
                        edit_order_id = order_options.get(selected_order) if selected_order != "None" else None
                    else:
                        st.info("No orders available")
                        edit_order_id = None
                    
                    edit_batch_name = st.text_input("Batch Name/ID*", value=selected_batch_data['batch_name'])
                    edit_num_explants = st.number_input("Number of Explants*", min_value=1, value=int(selected_batch_data['num_explants']))
                    edit_explant_type = st.selectbox(
                        "Explant Type*",
                        ["Node", "Microshoot", "Meristem", "Other"],
                        index=["Node", "Microshoot", "Meristem", "Other"].index(selected_batch_data['explant_type']) if selected_batch_data['explant_type'] in ["Node", "Microshoot", "Meristem", "Other"] else 0
                    )
                    edit_media_type = st.selectbox(
                        "Media Type*",
                        ["50% EECN", "100% EECN", "50% MS", "100% MS", "50% DKW", "100% DKW", "Rooting Media"],
                        index=["50% EECN", "100% EECN", "50% MS", "100% MS", "50% DKW", "100% DKW", "Rooting Media"].index(selected_batch_data['media_type']) if selected_batch_data['media_type'] in ["50% EECN", "100% EECN", "50% MS", "100% MS", "50% DKW", "100% DKW", "Rooting Media"] else 0
                    )
                    edit_initiation_date = st.date_input("Initiation Date*", value=pd.to_datetime(selected_batch_data['initiation_date']).date())
                    
                    st.subheader("Pathogen Status")
                    current_pathogen = selected_batch_data.get('pathogen_status', '') if pd.notna(selected_batch_data.get('pathogen_status')) else None
                    edit_pathogen_positive = st.checkbox("Pathogen Positive", value=current_pathogen is not None and current_pathogen != '')
                    edit_pathogen_status = None
                    if edit_pathogen_positive:
                        pathogen_options = [
                            "Hop Latent Viroid",
                            "Arabis Mosaic Virus",
                            "Beet Curly Top Virus",
                            "Lettuce Chlorosis Virus",
                            "Cannabis Cryptic Virus",
                            "Tomato Ringspot Virus",
                            "Tobacco Mosaic Virus",
                            "Tomato Mosaic Virus",
                            "Botrytis cineria",
                            "Pythium myriotylum",
                            "Fusarium oxysporum",
                            "Fusarium solani",
                            "Golovinomyces ambrosiae"
                        ]
                        default_pathogen = current_pathogen if current_pathogen in pathogen_options else "Select..."
                        edit_pathogen_status = st.selectbox("Select Pathogen", ["Select..."] + pathogen_options,
                                                             index=(["Select..."] + pathogen_options).index(default_pathogen) if default_pathogen in (["Select..."] + pathogen_options) else 0)
                        if edit_pathogen_status == "Select...":
                            edit_pathogen_status = None
                    
                    st.subheader("Media Additives")
                    col3, col4 = st.columns(2)
                    
                    with col3:
                        edit_hormones = st.text_area("Hormones and Concentrations", 
                                                     value=selected_batch_data.get('hormones', '') if pd.notna(selected_batch_data.get('hormones')) else "")
                    
                    with col4:
                        edit_additional_elements = st.text_area("Additional Elements and Concentrations",
                                                               value=selected_batch_data.get('additional_elements', '') if pd.notna(selected_batch_data.get('additional_elements')) else "")
                    
                    edit_notes = st.text_area("Notes", value=selected_batch_data['notes'] if pd.notna(selected_batch_data['notes']) else "")
                    
                    edit_submitted = st.form_submit_button("Update Batch")
                    
                    if edit_submitted:
                        if edit_batch_name and edit_media_type:
                            update_explant_batch(batch_id, edit_order_id, edit_batch_name, edit_num_explants, edit_explant_type,
                                               edit_media_type, edit_hormones or None, edit_additional_elements or None,
                                               str(edit_initiation_date), edit_notes, edit_pathogen_status)
                            st.success(f"Batch #{batch_id} updated successfully!")
                            st.rerun()
                        else:
                            st.error("Please fill in all required fields")
            
            with col2:
                st.write("**Delete Batch**")
                st.warning("Deleting a batch will also delete all associated infection records, transfer records, and rooting records. This action cannot be undone.")
                
                if st.button("Delete Batch", type="primary", use_container_width=True):
                    delete_explant_batch(batch_id)
                    st.success(f"Batch #{batch_id} deleted successfully!")
                    st.rerun()
        else:
            st.info("No batches found")

# Contamination Tracking
elif page == "Contamination Tracking":
    st.header("Contamination Tracking")
    
    tab1, tab2, tab3 = st.tabs(["Record Contamination", "View Contamination Records", "Edit/Delete Records"])
    
    with tab1:
        st.subheader("Record Contamination")
        
        batches = get_explant_batches()
        
        if not batches.empty:
            with st.form("infection_form"):
                col1, col2 = st.columns(2)
                
                with col1:
                    batch_options = {f"{row['batch_name']} (ID: {row['id']}) - {row['num_explants']} explants": row['id'] 
                                   for _, row in batches.iterrows()}
                    selected_batch = st.selectbox("Select Batch*", list(batch_options.keys()))
                    batch_id = batch_options[selected_batch]
                    
                    # Show current contamination count
                    total_lost = get_total_infections_for_batch(batch_id)
                    batch_info = batches[batches['id'] == batch_id].iloc[0]
                    remaining = batch_info['num_explants'] - total_lost
                    
                    st.info(f"Previously lost to contamination: {total_lost} | Remaining healthy: {remaining}")
                    
                    num_lost = st.number_input(
                        "Number of Explants Lost to Contamination*",
                        min_value=0,
                        max_value=remaining if remaining > 0 else 0,
                        value=0,
                        help="Explants that are completely lost and cannot be recovered"
                    )
                    
                    num_affected = st.number_input(
                        "Number of Explants Affected by Contamination*",
                        min_value=0,
                        value=0,
                        help="Explants that are affected but may still be recoverable"
                    )
                
                with col2:
                    infection_type = st.selectbox(
                        "Contamination Type*",
                        ["Bacterial", "Fungal"]
                    )
                    identification_date = st.date_input("Date Identified*", value=date.today())
                    notes = st.text_area("Notes (symptoms, appearance, etc.)")
                
                submitted = st.form_submit_button("Record Contamination")
                
                if submitted:
                    if num_lost == 0 and num_affected == 0:
                        st.error("Please enter at least one explant lost or affected")
                    elif remaining >= num_lost:
                        record_id = add_infection_record(
                            batch_id, num_lost, num_affected, infection_type,
                            str(identification_date), notes
                        )
                        st.success(f"Contamination record #{record_id} added successfully!")
                    else:
                        st.error("Cannot lose more explants than remaining healthy count")
        else:
            st.warning("No batches available. Please initiate a batch first.")
    
    with tab2:
        st.subheader("Contamination Records")
        
        # Filter by batch
        batches = get_explant_batches()
        if not batches.empty:
            batch_filter_options = {"All Batches": None}
            batch_filter_options.update({
                f"{row['batch_name']} (ID: {row['id']})": row['id'] 
                for _, row in batches.iterrows()
            })
            selected_filter = st.selectbox("Filter by Batch", list(batch_filter_options.keys()))
            filter_batch_id = batch_filter_options[selected_filter]
            
            infections = get_infection_records(filter_batch_id)
            
            if not infections.empty:
                st.dataframe(infections, use_container_width=True, hide_index=True)
                
                # Summary by contamination type
                st.subheader("Summary by Contamination Type")
                # Calculate totals for lost and affected
                infections['num_lost'] = infections['num_lost'].fillna(0)
                infections['num_affected'] = infections['num_affected'].fillna(0)
                summary = infections.groupby('infection_type').agg({
                    'num_lost': 'sum',
                    'num_affected': 'sum'
                }).reset_index()
                summary.columns = ['Contamination Type', 'Total Lost', 'Total Affected']
                summary['Total'] = summary['Total Lost'] + summary['Total Affected']
                st.dataframe(summary, use_container_width=True, hide_index=True)
            else:
                st.info("No contamination records found")
        else:
            st.info("No batches available")
    
    with tab3:
        st.subheader("Edit or Delete Contamination Records")
        infections = get_infection_records()
        batches = get_explant_batches()
        
        if not infections.empty:
            # Contamination record selection
            infection_options = {}
            for _, row in infections.iterrows():
                num_lost = row.get('num_lost', 0) if pd.notna(row.get('num_lost')) else (row.get('num_infected', 0) if pd.notna(row.get('num_infected')) else 0)
                num_affected = row.get('num_affected', 0) if pd.notna(row.get('num_affected')) else 0
                label = f"Record #{row['id']} - Batch {row['batch_id']} ({num_lost} lost, {num_affected} affected on {row['identification_date']})"
                infection_options[label] = row['id']
            selected_infection = st.selectbox("Select Contamination Record to Edit/Delete", list(infection_options.keys()))
            record_id = infection_options[selected_infection]
            
            selected_infection_data = infections[infections['id'] == record_id].iloc[0]
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Edit Contamination Record**")
                with st.form("edit_infection_form"):
                    batch_options = {f"{row['batch_name']} (ID: {row['id']})": row['id'] 
                                   for _, row in batches.iterrows()}
                    current_batch_id = selected_infection_data['batch_id']
                    current_batch = batches[batches['id'] == current_batch_id]
                    if not current_batch.empty:
                        current_batch_key = f"{current_batch.iloc[0]['batch_name']} (ID: {current_batch.iloc[0]['id']})"
                        default_batch = current_batch_key if current_batch_key in batch_options else list(batch_options.keys())[0]
                    else:
                        default_batch = list(batch_options.keys())[0]
                    
                    edit_batch_id = st.selectbox("Select Batch*", list(batch_options.keys()), 
                                                 index=list(batch_options.keys()).index(default_batch) if default_batch in batch_options else 0)
                    edit_batch_id = batch_options[edit_batch_id]
                    
                    # Get remaining healthy for validation
                    total_lost = get_total_infections_for_batch(edit_batch_id)
                    batch_info = batches[batches['id'] == edit_batch_id].iloc[0]
                    # Add back the current record's lost count for validation
                    current_lost = selected_infection_data.get('num_lost', 0) if pd.notna(selected_infection_data.get('num_lost')) else (selected_infection_data.get('num_infected', 0) if pd.notna(selected_infection_data.get('num_infected')) else 0)
                    remaining = batch_info['num_explants'] - total_lost + current_lost
                    
                    # Get current values with backward compatibility
                    current_num_lost = selected_infection_data.get('num_lost', 0) if pd.notna(selected_infection_data.get('num_lost')) else (selected_infection_data.get('num_infected', 0) if pd.notna(selected_infection_data.get('num_infected')) else 0)
                    current_num_affected = selected_infection_data.get('num_affected', 0) if pd.notna(selected_infection_data.get('num_affected')) else 0
                    
                    edit_num_lost = st.number_input(
                        "Number of Explants Lost to Contamination*",
                        min_value=0,
                        max_value=remaining if remaining > 0 else 0,
                        value=int(current_num_lost),
                        help="Explants that are completely lost and cannot be recovered"
                    )
                    
                    edit_num_affected = st.number_input(
                        "Number of Explants Affected by Contamination*",
                        min_value=0,
                        value=int(current_num_affected),
                        help="Explants that are affected but may still be recoverable"
                    )
                    
                    edit_infection_type = st.selectbox(
                        "Contamination Type*",
                        ["Bacterial", "Fungal"],
                        index=["Bacterial", "Fungal"].index(selected_infection_data['infection_type']) if selected_infection_data['infection_type'] in ["Bacterial", "Fungal"] else 0
                    )
                    edit_identification_date = st.date_input("Date Identified*", value=pd.to_datetime(selected_infection_data['identification_date']).date())
                    edit_notes = st.text_area("Notes", value=selected_infection_data['notes'] if pd.notna(selected_infection_data['notes']) else "")
                    
                    edit_submitted = st.form_submit_button("Update Contamination Record")
                    
                    if edit_submitted:
                        if edit_num_lost == 0 and edit_num_affected == 0:
                            st.error("Please enter at least one explant lost or affected")
                        elif edit_num_lost <= remaining:
                            update_infection_record(record_id, edit_batch_id, edit_num_lost, edit_num_affected, edit_infection_type, str(edit_identification_date), edit_notes)
                            st.success(f"Contamination record #{record_id} updated successfully!")
                            st.rerun()
                        else:
                            st.error("Cannot lose more explants than remaining healthy count")
            
            with col2:
                st.write("**Delete Contamination Record**")
                st.warning("This action cannot be undone.")
                
                if st.button("Delete Contamination Record", type="primary", use_container_width=True):
                    delete_infection_record(record_id)
                    st.success(f"Contamination record #{record_id} deleted successfully!")
                    st.rerun()
        else:
            st.info("No infection records found")

# Transfer Management
elif page == "Transfer Management":
    st.header("Transfer Management")
    
    tab1, tab2, tab3 = st.tabs(["Record Transfer", "View Transfers", "Edit/Delete Transfers"])
    
    with tab1:
        st.subheader("Record Transfer to New Media")
        
        batches = get_explant_batches()
        
        if not batches.empty:
            with st.form("transfer_form"):
                col1, col2 = st.columns(2)
                
                with col1:
                    batch_options = {f"{row['batch_name']} (ID: {row['id']})": row['id'] 
                                   for _, row in batches.iterrows()}
                    selected_batch = st.selectbox("Select Batch*", list(batch_options.keys()))
                    batch_id = batch_options[selected_batch]
                    
                    # Get batch summary
                    summary = get_batch_summary(batch_id)
                    if summary:
                        st.info(f"Total initiated: {summary['batch'][3]} | Healthy: {summary['healthy']}")
                    
                    # Option to link to previous transfer
                    transfers = get_transfer_records(batch_id)
                    if not transfers.empty:
                        transfer_options = {"New transfer (from original batch)": None}
                        transfer_options.update({
                            f"Transfer #{row['id']} ({row['transfer_date']}) - {row['explants_out']} out": row['id']
                            for _, row in transfers.iterrows()
                        })
                        selected_parent = st.selectbox("Parent Transfer", list(transfer_options.keys()))
                        parent_transfer_id = transfer_options[selected_parent]
                    else:
                        parent_transfer_id = None
                        st.caption("This will be the first transfer for this batch")
                    
                    explants_in = st.number_input("Explants In*", min_value=1, value=1)
                
                with col2:
                    explants_out = st.number_input("Explants Out*", min_value=1, value=1)
                    new_media = st.selectbox(
                        "New Media Type*",
                        ["50% EECN", "100% EECN", "50% MS", "100% MS", "50% DKW", "100% DKW", "Rooting Media"]
                    )
                    transfer_date = st.date_input("Transfer Date*", value=date.today())
                    multiplication_occurred = st.checkbox("Multiplication Occurred")
                
                st.subheader("Media Additives")
                col3, col4 = st.columns(2)
                
                with col3:
                    hormones = st.text_area("Hormones and Concentrations", placeholder="e.g., BAP 2.0 mg/L, IBA 0.5 mg/L")
                
                with col4:
                    additional_elements = st.text_area("Additional Elements and Concentrations", placeholder="e.g., Activated charcoal 0.5 g/L, Sucrose 30 g/L")
                
                notes = st.text_area("Notes")
                
                # Show multiplication ratio
                if explants_in > 0:
                    ratio = explants_out / explants_in
                    st.metric("Multiplication Ratio", f"{ratio:.2f}x")
                
                submitted = st.form_submit_button("Record Transfer")
                
                if submitted:
                    if new_media:
                        transfer_id = add_transfer_record(
                            batch_id, parent_transfer_id, str(transfer_date),
                            explants_in, explants_out, new_media,
                            hormones or None, additional_elements or None,
                            1 if multiplication_occurred else 0, notes
                        )
                        st.success(f"Transfer #{transfer_id} recorded successfully!")
                        st.info(f"In: {explants_in} → Out: {explants_out} (Ratio: {explants_out/explants_in:.2f}x)")
                    else:
                        st.error("Please specify the new media type")
        else:
            st.warning("No batches available. Please initiate a batch first.")
    
    with tab2:
        st.subheader("Transfer Records")
        
        # Filter by batch
        batches = get_explant_batches()
        if not batches.empty:
            batch_filter_options = {"All Batches": None}
            batch_filter_options.update({
                f"{row['batch_name']} (ID: {row['id']})": row['id'] 
                for _, row in batches.iterrows()
            })
            selected_filter = st.selectbox("Filter by Batch", list(batch_filter_options.keys()))
            filter_batch_id = batch_filter_options[selected_filter]
            
            transfers = get_transfer_records(filter_batch_id)
            
            if not transfers.empty:
                # Add multiplication ratio column
                transfers['ratio'] = transfers['explants_out'] / transfers['explants_in']
                transfers['multiplication'] = transfers['multiplication_occurred'].apply(lambda x: "Yes" if x else "No")
                
                display_cols = ['id', 'batch_id', 'transfer_date', 'explants_in', 
                               'explants_out', 'ratio', 'new_media', 'hormones', 'additional_elements', 'multiplication', 'notes']
                st.dataframe(transfers[display_cols], use_container_width=True, hide_index=True)
                
                # Summary statistics
                st.subheader("Transfer Summary")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Transfers", len(transfers))
                with col2:
                    avg_ratio = transfers['ratio'].mean()
                    st.metric("Avg Multiplication Ratio", f"{avg_ratio:.2f}x")
                with col3:
                    total_out = transfers['explants_out'].sum()
                    st.metric("Total Explants Out", int(total_out))
            else:
                st.info("No transfer records found")
        else:
            st.info("No batches available")
    
    with tab3:
        st.subheader("Edit or Delete Transfer Records")
        transfers = get_transfer_records()
        batches = get_explant_batches()
        
        if not transfers.empty:
            # Transfer selection
            transfer_options = {f"Transfer #{row['id']} - Batch {row['batch_id']} ({row['explants_in']} in → {row['explants_out']} out on {row['transfer_date']})": row['id'] 
                              for _, row in transfers.iterrows()}
            selected_transfer = st.selectbox("Select Transfer to Edit/Delete", list(transfer_options.keys()))
            transfer_id = transfer_options[selected_transfer]
            
            selected_transfer_data = transfers[transfers['id'] == transfer_id].iloc[0]
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Edit Transfer**")
                with st.form("edit_transfer_form"):
                    batch_options = {f"{row['batch_name']} (ID: {row['id']})": row['id'] 
                                   for _, row in batches.iterrows()}
                    current_batch_id = selected_transfer_data['batch_id']
                    current_batch = batches[batches['id'] == current_batch_id]
                    if not current_batch.empty:
                        current_batch_key = f"{current_batch.iloc[0]['batch_name']} (ID: {current_batch.iloc[0]['id']})"
                        default_batch = current_batch_key if current_batch_key in batch_options else list(batch_options.keys())[0]
                    else:
                        default_batch = list(batch_options.keys())[0]
                    
                    edit_batch_id = st.selectbox("Select Batch*", list(batch_options.keys()), 
                                                 index=list(batch_options.keys()).index(default_batch) if default_batch in batch_options else 0)
                    edit_batch_id = batch_options[edit_batch_id]
                    
                    # Parent transfer selection
                    batch_transfers = get_transfer_records(edit_batch_id)
                    if not batch_transfers.empty:
                        parent_options = {"New transfer (from original batch)": None}
                        parent_options.update({
                            f"Transfer #{row['id']} ({row['transfer_date']})": row['id']
                            for _, row in batch_transfers.iterrows() if row['id'] != transfer_id
                        })
                        current_parent = selected_transfer_data.get('parent_transfer_id')
                        if pd.notna(current_parent):
                            current_parent_key = f"Transfer #{int(current_parent)}"
                            default_parent = current_parent_key if current_parent_key in parent_options else "New transfer (from original batch)"
                        else:
                            default_parent = "New transfer (from original batch)"
                        edit_parent_transfer_id = st.selectbox("Parent Transfer", list(parent_options.keys()),
                                                               index=list(parent_options.keys()).index(default_parent) if default_parent in parent_options else 0)
                        edit_parent_transfer_id = parent_options[edit_parent_transfer_id]
                    else:
                        edit_parent_transfer_id = None
                    
                    edit_explants_in = st.number_input("Explants In*", min_value=1, value=int(selected_transfer_data['explants_in']))
                    edit_explants_out = st.number_input("Explants Out*", min_value=1, value=int(selected_transfer_data['explants_out']))
                    edit_new_media = st.selectbox(
                        "New Media Type*",
                        ["50% EECN", "100% EECN", "50% MS", "100% MS", "50% DKW", "100% DKW", "Rooting Media"],
                        index=["50% EECN", "100% EECN", "50% MS", "100% MS", "50% DKW", "100% DKW", "Rooting Media"].index(selected_transfer_data['new_media']) if selected_transfer_data['new_media'] in ["50% EECN", "100% EECN", "50% MS", "100% MS", "50% DKW", "100% DKW", "Rooting Media"] else 0
                    )
                    edit_transfer_date = st.date_input("Transfer Date*", value=pd.to_datetime(selected_transfer_data['transfer_date']).date())
                    edit_multiplication_occurred = st.checkbox("Multiplication Occurred", value=bool(selected_transfer_data['multiplication_occurred']))
                    
                    st.subheader("Media Additives")
                    col3, col4 = st.columns(2)
                    
                    with col3:
                        edit_hormones = st.text_area("Hormones and Concentrations",
                                                     value=selected_transfer_data.get('hormones', '') if pd.notna(selected_transfer_data.get('hormones')) else "")
                    
                    with col4:
                        edit_additional_elements = st.text_area("Additional Elements and Concentrations",
                                                               value=selected_transfer_data.get('additional_elements', '') if pd.notna(selected_transfer_data.get('additional_elements')) else "")
                    
                    edit_notes = st.text_area("Notes", value=selected_transfer_data['notes'] if pd.notna(selected_transfer_data['notes']) else "")
                    
                    edit_submitted = st.form_submit_button("Update Transfer")
                    
                    if edit_submitted:
                        if edit_new_media:
                            update_transfer_record(transfer_id, edit_batch_id, edit_parent_transfer_id, str(edit_transfer_date),
                                                  edit_explants_in, edit_explants_out, edit_new_media,
                                                  edit_hormones or None, edit_additional_elements or None,
                                                  1 if edit_multiplication_occurred else 0, edit_notes)
                            st.success(f"Transfer #{transfer_id} updated successfully!")
                            st.rerun()
                        else:
                            st.error("Please specify the new media type")
            
            with col2:
                st.write("**Delete Transfer**")
                st.warning("Deleting a transfer will also delete all associated rooting records. This action cannot be undone.")
                
                if st.button("Delete Transfer", type="primary", use_container_width=True):
                    delete_transfer_record(transfer_id)
                    st.success(f"Transfer #{transfer_id} deleted successfully!")
                    st.rerun()
        else:
            st.info("No transfer records found")

# Reports
elif page == "Reports":
    st.header("Reports & Analytics")
    
    tab1, tab2, tab3 = st.tabs(["Batch Summary", "Infection Analysis", "Transfer Analysis"])
    
    with tab1:
        st.subheader("Batch Summary Report")
        
        batches = get_explant_batches()
        
        if not batches.empty:
            # Build comprehensive summary
            summary_data = []
            
            for _, batch in batches.iterrows():
                batch_id = batch['id']
                total_infected = get_total_infections_for_batch(batch_id)
                transfers = get_transfer_records(batch_id)
                
                total_transferred = transfers['explants_out'].sum() if not transfers.empty else 0
                avg_ratio = transfers['explants_out'].sum() / transfers['explants_in'].sum() if not transfers.empty and transfers['explants_in'].sum() > 0 else 0
                
                summary_data.append({
                    'Batch ID': batch_id,
                    'Batch Name': batch['batch_name'],
                    'Initial Count': batch['num_explants'],
                    'Type': batch['explant_type'],
                    'Media': batch['media_type'],
                    'Hormones': batch.get('hormones', '') or '',
                    'Additional Elements': batch.get('additional_elements', '') or '',
                    'Date': batch['initiation_date'],
                    'Infected': total_infected,
                    'Infection %': f"{(total_infected/batch['num_explants']*100):.1f}%" if batch['num_explants'] > 0 else "0%",
                    'Healthy': batch['num_explants'] - total_infected,
                    'Transfers': len(transfers),
                    'Total Out': int(total_transferred),
                    'Avg Ratio': f"{avg_ratio:.2f}x"
                })
            
            summary_df = pd.DataFrame(summary_data)
            st.dataframe(summary_df, use_container_width=True, hide_index=True)
            
            # Export
            csv = summary_df.to_csv(index=False)
            st.download_button(
                "Download Summary CSV",
                csv,
                "batch_summary.csv",
                "text/csv"
            )
        else:
            st.info("No batches to report on")
    
    with tab2:
        st.subheader("Infection Analysis")
        
        infections = get_infection_records()
        
        if not infections.empty:
            col1, col2 = st.columns(2)
            
            with col1:
                # Infection by type
                st.write("**Infections by Type**")
                type_summary = infections.groupby('infection_type')['num_infected'].sum().reset_index()
                type_summary.columns = ['Type', 'Count']
                st.bar_chart(type_summary.set_index('Type'))
            
            with col2:
                # Infection timeline
                st.write("**Infection Timeline**")
                timeline = infections.groupby('identification_date')['num_infected'].sum().reset_index()
                timeline.columns = ['Date', 'Infected']
                timeline['Date'] = pd.to_datetime(timeline['Date'])
                timeline = timeline.sort_values('Date')
                st.line_chart(timeline.set_index('Date'))
            
            # Detailed table
            st.write("**Detailed Infection Records**")
            st.dataframe(infections, use_container_width=True, hide_index=True)
        else:
            st.info("No infection records to analyze")
    
    with tab3:
        st.subheader("Transfer Analysis")
        
        transfers = get_transfer_records()
        
        if not transfers.empty:
            col1, col2 = st.columns(2)
            
            with col1:
                # Multiplication ratios
                st.write("**Multiplication Ratios**")
                transfers['ratio'] = transfers['explants_out'] / transfers['explants_in']
                st.bar_chart(transfers[['id', 'ratio']].set_index('id'))
            
            with col2:
                # Media usage
                st.write("**Media Usage**")
                media_summary = transfers.groupby('new_media')['explants_out'].sum().reset_index()
                media_summary.columns = ['Media', 'Explants Out']
                st.dataframe(media_summary, use_container_width=True, hide_index=True)
            
            # Transfer efficiency
            st.write("**Overall Transfer Efficiency**")
            total_in = transfers['explants_in'].sum()
            total_out = transfers['explants_out'].sum()
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total In", int(total_in))
            with col2:
                st.metric("Total Out", int(total_out))
            with col3:
                overall_ratio = total_out / total_in if total_in > 0 else 0
                st.metric("Overall Ratio", f"{overall_ratio:.2f}x")
        else:
            st.info("No transfer records to analyze")

# Rooting Tracking
elif page == "Rooting Tracking":
    st.header("Rooting Tracking")
    
    tab1, tab2, tab3 = st.tabs(["Record Rooting", "View Rooting Records", "Edit/Delete Records"])
    
    with tab1:
        st.subheader("Record Plants Placed in Rooting Media")
        
        # Get transfers that used rooting media
        transfers = get_transfer_records()
        rooting_transfers = transfers[transfers['new_media'] == 'Rooting Media'] if not transfers.empty else pd.DataFrame()
        
        if not rooting_transfers.empty:
            # Get batch info for display
            batches = get_explant_batches()
            transfer_options = {}
            for _, transfer in rooting_transfers.iterrows():
                batch_info = batches[batches['id'] == transfer['batch_id']]
                if not batch_info.empty:
                    batch_name = batch_info.iloc[0]['batch_name']
                    transfer_options[f"Transfer #{transfer['id']} - Batch: {batch_name} ({transfer['explants_out']} explants)"] = transfer['id']
            
            selected_transfer = st.selectbox("Select Transfer*", list(transfer_options.keys()))
            transfer_id = transfer_options[selected_transfer]
            selected_transfer_data = rooting_transfers[rooting_transfers['id'] == transfer_id].iloc[0]
            
            # Get existing rooting records for this transfer
            existing_rooting = get_rooting_records(transfer_id=transfer_id)
            if not existing_rooting.empty:
                already_placed = existing_rooting['num_placed'].sum()
                remaining = selected_transfer_data['explants_out'] - already_placed
                st.info(f"Already placed: {already_placed} | Remaining: {remaining}")
            else:
                remaining = selected_transfer_data['explants_out']
            
            with st.form("rooting_form"):
                col1, col2 = st.columns(2)
                
                with col1:
                    # Auto-fill with remaining explants from transfer
                    default_placed = remaining if remaining > 0 else 1
                    num_placed = st.number_input("Number Placed in Rooting Media*", min_value=1, max_value=remaining if remaining > 0 else 1, value=default_placed)
                    # Auto-fill placement date from transfer date
                    transfer_date = pd.to_datetime(selected_transfer_data['transfer_date']).date()
                    placement_date = st.date_input("Placement Date*", value=transfer_date)
                
                with col2:
                    batch_id = int(selected_transfer_data['batch_id'])
                    num_rooted = st.number_input("Number Rooted (optional)", min_value=0, value=0)
                    rooting_date = st.date_input("Rooting Date (optional)", value=None)
                    notes = st.text_area("Notes")
                
                submitted = st.form_submit_button("Record Rooting")
                
                if submitted:
                    if num_placed <= remaining:
                        record_id = add_rooting_record(
                            transfer_id, batch_id, num_placed, placement_date,
                            num_rooted if num_rooted > 0 else None,
                            rooting_date, notes
                        )
                        st.success(f"Rooting record #{record_id} added successfully!")
                    else:
                        st.error("Cannot place more explants than available")
        else:
            st.warning("No transfers to rooting media found. Please create a transfer with 'Rooting Media' first.")
    
    with tab2:
        st.subheader("Rooting Records")
        
        # Filter by batch
        batches = get_explant_batches()
        if not batches.empty:
            batch_filter_options = {"All Batches": None}
            batch_filter_options.update({
                f"{row['batch_name']} (ID: {row['id']})": row['id'] 
                for _, row in batches.iterrows()
            })
            selected_filter = st.selectbox("Filter by Batch", list(batch_filter_options.keys()))
            filter_batch_id = batch_filter_options[selected_filter]
            
            rooting_records = get_rooting_records(filter_batch_id)
            
            if not rooting_records.empty:
                # Add rooting rate column
                rooting_records['rooting_rate'] = (rooting_records['num_rooted'] / rooting_records['num_placed'] * 100).round(1)
                rooting_records['rooting_rate'] = rooting_records['rooting_rate'].fillna(0)
                rooting_records['status'] = rooting_records.apply(
                    lambda x: "Rooted" if pd.notna(x['num_rooted']) and x['num_rooted'] > 0 else "In Progress",
                    axis=1
                )
                
                display_cols = ['id', 'batch_id', 'transfer_id', 'num_placed', 'placement_date', 
                               'num_rooted', 'rooting_date', 'rooting_rate', 'status', 'notes']
                st.dataframe(rooting_records[display_cols], use_container_width=True, hide_index=True)
                
                # Summary statistics
                st.subheader("Rooting Summary")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    total_placed = rooting_records['num_placed'].sum()
                    st.metric("Total Placed", int(total_placed))
                with col2:
                    total_rooted = rooting_records['num_rooted'].sum() if 'num_rooted' in rooting_records.columns else 0
                    st.metric("Total Rooted", int(total_rooted) if pd.notna(total_rooted) else 0)
                with col3:
                    overall_rate = (total_rooted / total_placed * 100) if total_placed > 0 and pd.notna(total_rooted) else 0
                    st.metric("Overall Rooting Rate", f"{overall_rate:.1f}%")
                with col4:
                    in_progress = total_placed - (total_rooted if pd.notna(total_rooted) else 0)
                    st.metric("In Progress", int(in_progress))
                
                # Update rooting records
                st.subheader("Update Rooting Status")
                with st.form("update_rooting_form"):
                    record_options = {f"Record #{row['id']} - {row['num_placed']} placed on {row['placement_date']}": row['id']
                                     for _, row in rooting_records.iterrows()}
                    selected_record = st.selectbox("Select Record to Update", list(record_options.keys()))
                    record_id = record_options[selected_record]
                    
                    selected_record_data = rooting_records[rooting_records['id'] == record_id].iloc[0]
                    max_rooted = selected_record_data['num_placed']
                    
                    new_num_rooted = st.number_input("Number Rooted*", min_value=0, max_value=max_rooted, 
                                                    value=int(selected_record_data['num_rooted']) if pd.notna(selected_record_data['num_rooted']) else 0)
                    new_rooting_date = st.date_input("Rooting Date*", 
                                                    value=pd.to_datetime(selected_record_data['rooting_date']).date() if pd.notna(selected_record_data['rooting_date']) else date.today())
                    
                    update_submitted = st.form_submit_button("Update Rooting Status")
                    
                    if update_submitted:
                        update_rooting_record(record_id, new_num_rooted, new_rooting_date)
                        st.success(f"Rooting record #{record_id} updated successfully!")
                        st.rerun()
            else:
                st.info("No rooting records found")
        else:
            st.info("No batches available")
    
    with tab3:
        st.subheader("Edit or Delete Rooting Records")
        rooting_records = get_rooting_records()
        batches = get_explant_batches()
        transfers = get_transfer_records()
        
        if not rooting_records.empty:
            # Rooting record selection
            record_options = {f"Record #{row['id']} - Batch {row['batch_id']} ({row['num_placed']} placed on {row['placement_date']})": row['id'] 
                            for _, row in rooting_records.iterrows()}
            selected_record = st.selectbox("Select Rooting Record to Edit/Delete", list(record_options.keys()))
            record_id = record_options[selected_record]
            
            selected_record_data = rooting_records[rooting_records['id'] == record_id].iloc[0]
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Edit Rooting Record**")
                with st.form("edit_rooting_form"):
                    # Transfer selection
                    rooting_transfers = transfers[transfers['new_media'] == 'Rooting Media'] if not transfers.empty else pd.DataFrame()
                    if not rooting_transfers.empty:
                        transfer_options = {f"Transfer #{row['id']} - Batch {row['batch_id']}": row['id'] 
                                          for _, row in rooting_transfers.iterrows()}
                        current_transfer_id = selected_record_data.get('transfer_id')
                        if pd.notna(current_transfer_id):
                            current_transfer_key = f"Transfer #{int(current_transfer_id)}"
                            default_transfer = current_transfer_key if current_transfer_key in transfer_options else list(transfer_options.keys())[0]
                        else:
                            default_transfer = list(transfer_options.keys())[0]
                        edit_transfer_id = st.selectbox("Select Transfer*", list(transfer_options.keys()),
                                                        index=list(transfer_options.keys()).index(default_transfer) if default_transfer in transfer_options else 0)
                        edit_transfer_id = transfer_options[edit_transfer_id]
                    else:
                        edit_transfer_id = None
                        st.info("No transfers to rooting media available")
                    
                    # Batch selection
                    batch_options = {f"{row['batch_name']} (ID: {row['id']})": row['id'] 
                                   for _, row in batches.iterrows()}
                    current_batch_id = selected_record_data['batch_id']
                    current_batch = batches[batches['id'] == current_batch_id]
                    if not current_batch.empty:
                        current_batch_key = f"{current_batch.iloc[0]['batch_name']} (ID: {current_batch.iloc[0]['id']})"
                        default_batch = current_batch_key if current_batch_key in batch_options else list(batch_options.keys())[0]
                    else:
                        default_batch = list(batch_options.keys())[0]
                    
                    edit_batch_id = st.selectbox("Select Batch*", list(batch_options.keys()), 
                                                 index=list(batch_options.keys()).index(default_batch) if default_batch in batch_options else 0)
                    edit_batch_id = batch_options[edit_batch_id]
                    
                    edit_num_placed = st.number_input("Number Placed*", min_value=1, value=int(selected_record_data['num_placed']))
                    edit_placement_date = st.date_input("Placement Date*", value=pd.to_datetime(selected_record_data['placement_date']).date())
                    edit_num_rooted = st.number_input("Number Rooted (optional)", min_value=0, max_value=edit_num_placed,
                                                      value=int(selected_record_data['num_rooted']) if pd.notna(selected_record_data['num_rooted']) else 0)
                    edit_rooting_date = st.date_input("Rooting Date (optional)", 
                                                      value=pd.to_datetime(selected_record_data['rooting_date']).date() if pd.notna(selected_record_data['rooting_date']) else None)
                    edit_notes = st.text_area("Notes", value=selected_record_data['notes'] if pd.notna(selected_record_data['notes']) else "")
                    
                    edit_submitted = st.form_submit_button("Update Rooting Record")
                    
                    if edit_submitted:
                        update_rooting_record_full(record_id, edit_transfer_id, edit_batch_id, edit_num_placed, edit_placement_date,
                                                   edit_num_rooted if edit_num_rooted > 0 else None, edit_rooting_date, edit_notes)
                        st.success(f"Rooting record #{record_id} updated successfully!")
                        st.rerun()
            
            with col2:
                st.write("**Delete Rooting Record**")
                st.warning("This action cannot be undone.")
                
                if st.button("Delete Rooting Record", type="primary", use_container_width=True):
                    delete_rooting_record(record_id)
                    st.success(f"Rooting record #{record_id} deleted successfully!")
                    st.rerun()
        else:
            st.info("No rooting records found")

# Delivery
elif page == "Delivery":
    st.header("Delivery Tracking")
    
    tab1, tab2, tab3 = st.tabs(["Record Delivery", "View Delivery Records", "Edit/Delete Records"])
    
    with tab1:
        st.subheader("Record Delivery")
        
        # Get orders and batches
        orders = get_orders()
        batches = get_explant_batches()
        
        if not orders.empty:
            with st.form("delivery_form"):
                col1, col2 = st.columns(2)
                
                with col1:
                    # Order selection
                    order_options = {f"Order #{row['id']} - {row['client_name']} ({row['cultivar']})": row['id'] 
                                    for _, row in orders.iterrows()}
                    selected_order = st.selectbox("Select Order*", list(order_options.keys()))
                    order_id = order_options[selected_order]
                    
                    # Batch selection (batches linked to this order)
                    order_batches = batches[batches['order_id'] == order_id] if not batches.empty else pd.DataFrame()
                    if not order_batches.empty:
                        batch_options = {f"{row['batch_name']} (ID: {row['id']})": row['id'] 
                                        for _, row in order_batches.iterrows()}
                        batch_options["None"] = None
                        selected_batch = st.selectbox("Select Batch (optional)", list(batch_options.keys()))
                        batch_id = batch_options[selected_batch]
                    else:
                        batch_id = None
                        st.info("No batches found for this order")
                    
                    num_delivered = st.number_input("Number Delivered*", min_value=1, value=1)
                    delivery_date = st.date_input("Delivery Date*", value=date.today())
                
                with col2:
                    delivery_method = st.text_input("Delivery Method (e.g., Shipping, Pickup, etc.)")
                    notes = st.text_area("Notes")
                
                submitted = st.form_submit_button("Record Delivery")
                
                if submitted:
                    record_id = add_delivery_record(
                        order_id, batch_id, num_delivered, delivery_date, delivery_method, notes
                    )
                    st.success(f"Delivery record #{record_id} added successfully!")
                    st.rerun()
        else:
            st.warning("No orders found. Please create an order first.")
    
    with tab2:
        st.subheader("Delivery Records")
        delivery_records = get_delivery_records()
        
        if not delivery_records.empty:
            # Merge with orders and batches for display
            delivery_display = delivery_records.merge(
                orders, left_on='order_id', right_on='id', how='left', suffixes=('', '_order')
            )
            delivery_display = delivery_display.merge(
                batches, left_on='batch_id', right_on='id', how='left', suffixes=('', '_batch')
            )
            
            display_cols = ['id', 'order_id', 'client_name', 'cultivar', 'batch_name', 
                          'num_delivered', 'delivery_date', 'delivery_method', 'notes']
            available_cols = [col for col in display_cols if col in delivery_display.columns]
            st.dataframe(delivery_display[available_cols], use_container_width=True, hide_index=True)
            
            # Summary
            st.subheader("Delivery Summary")
            col1, col2 = st.columns(2)
            with col1:
                total_delivered = delivery_records['num_delivered'].sum()
                st.metric("Total Plants Delivered", total_delivered)
            with col2:
                total_deliveries = len(delivery_records)
                st.metric("Total Delivery Records", total_deliveries)
        else:
            st.info("No delivery records found")
    
    with tab3:
        st.subheader("Edit or Delete Delivery Records")
        delivery_records = get_delivery_records()
        
        if not delivery_records.empty:
            # Delivery record selection
            delivery_options = {}
            orders = get_orders()
            batches = get_explant_batches()
            
            for _, delivery in delivery_records.iterrows():
                order_info = orders[orders['id'] == delivery['order_id']]
                batch_info = batches[batches['id'] == delivery['batch_id']] if pd.notna(delivery['batch_id']) else pd.DataFrame()
                
                order_str = f"Order #{delivery['order_id']}"
                if not order_info.empty:
                    order_str += f" - {order_info.iloc[0]['client_name']}"
                
                batch_str = ""
                if not batch_info.empty:
                    batch_str = f" - Batch: {batch_info.iloc[0]['batch_name']}"
                
                delivery_options[f"Delivery #{delivery['id']} - {order_str}{batch_str} ({delivery['num_delivered']} plants)"] = delivery['id']
            
            selected_delivery = st.selectbox("Select Delivery Record to Edit/Delete", list(delivery_options.keys()))
            record_id = delivery_options[selected_delivery]
            
            selected_record_data = delivery_records[delivery_records['id'] == record_id].iloc[0]
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Edit Delivery Record**")
                with st.form("edit_delivery_form"):
                    # Order selection
                    order_options = {f"Order #{row['id']} - {row['client_name']} ({row['cultivar']})": row['id'] 
                                    for _, row in orders.iterrows()}
                    current_order_id = selected_record_data['order_id']
                    current_order_key = f"Order #{current_order_id}"
                    for key in order_options.keys():
                        if key.startswith(current_order_key):
                            current_order_key = key
                            break
                    default_order = current_order_key if current_order_key in order_options else list(order_options.keys())[0]
                    
                    edit_order_id = st.selectbox("Select Order*", list(order_options.keys()),
                                                 index=list(order_options.keys()).index(default_order) if default_order in order_options else 0)
                    edit_order_id = order_options[edit_order_id]
                    
                    # Batch selection
                    order_batches = batches[batches['order_id'] == edit_order_id] if not batches.empty else pd.DataFrame()
                    if not order_batches.empty:
                        batch_options = {f"{row['batch_name']} (ID: {row['id']})": row['id'] 
                                        for _, row in order_batches.iterrows()}
                        batch_options["None"] = None
                        current_batch_id = selected_record_data.get('batch_id')
                        if pd.notna(current_batch_id):
                            current_batch = batches[batches['id'] == current_batch_id]
                            if not current_batch.empty:
                                current_batch_key = f"{current_batch.iloc[0]['batch_name']} (ID: {current_batch.iloc[0]['id']})"
                                default_batch = current_batch_key if current_batch_key in batch_options else "None"
                            else:
                                default_batch = "None"
                        else:
                            default_batch = "None"
                        
                        edit_batch_id = st.selectbox("Select Batch (optional)", list(batch_options.keys()),
                                                     index=list(batch_options.keys()).index(default_batch) if default_batch in batch_options else 0)
                        edit_batch_id = batch_options[edit_batch_id]
                    else:
                        edit_batch_id = None
                        st.info("No batches found for this order")
                    
                    edit_num_delivered = st.number_input("Number Delivered*", min_value=1, value=int(selected_record_data['num_delivered']))
                    edit_delivery_date = st.date_input("Delivery Date*", value=pd.to_datetime(selected_record_data['delivery_date']).date())
                    edit_delivery_method = st.text_input("Delivery Method", value=selected_record_data.get('delivery_method', '') if pd.notna(selected_record_data.get('delivery_method')) else "")
                    edit_notes = st.text_area("Notes", value=selected_record_data.get('notes', '') if pd.notna(selected_record_data.get('notes')) else "")
                    
                    edit_submitted = st.form_submit_button("Update Delivery Record")
                    
                    if edit_submitted:
                        update_delivery_record(record_id, edit_order_id, edit_batch_id, edit_num_delivered, edit_delivery_date, edit_delivery_method, edit_notes)
                        st.success(f"Delivery record #{record_id} updated successfully!")
                        st.rerun()
            
            with col2:
                st.write("**Delete Delivery Record**")
                st.warning("This action cannot be undone.")
                
                if st.button("Delete Delivery Record", type="primary", use_container_width=True):
                    delete_delivery_record(record_id)
                    st.success(f"Delivery record #{record_id} deleted successfully!")
                    st.rerun()
        else:
            st.info("No delivery records found")

# Labels - QR Code Generation
elif page == "Labels":
    st.header("Label Generator")
    
    tab1, tab2, tab3 = st.tabs(["Generate Labels", "View Generated Labels", "Scan QR Code"])
    
    with tab1:
        st.subheader("Generate Labels for Order")
        
        orders = get_orders()
        active_orders = orders[orders.get('completed', 0) == 0] if 'completed' in orders.columns else orders
        
        if not active_orders.empty:
            # Cultivar selection
            unique_cultivars = active_orders['cultivar'].unique().tolist()
            unique_cultivars.sort()
            
            selected_cultivar = st.selectbox(
                "Select Cultivar",
                options=unique_cultivars
            )
            
            if selected_cultivar:
                # Get orders for selected cultivar (most recent first)
                cultivar_orders = active_orders[active_orders['cultivar'] == selected_cultivar].sort_values('order_date', ascending=False)
                
                if not cultivar_orders.empty:
                    # Use the most recent order for this cultivar
                    order = cultivar_orders.iloc[0]
                    order_id = order['id']
                    
                    # Display cultivar and order info
                    if len(cultivar_orders) > 1:
                        st.info(f"**Cultivar:** {selected_cultivar} | **Client:** {order['client_name']} | **Order:** #{order_id} (Most recent of {len(cultivar_orders)} orders) | **Plants:** {order['num_plants']}")
                    else:
                        st.info(f"**Cultivar:** {selected_cultivar} | **Client:** {order['client_name']} | **Order:** #{order_id} | **Plants:** {order['num_plants']}")
                    
                    # Get pathogens for this order
                    detected_pathogens = get_pathogens_for_order(order_id)
                    
                    st.divider()
                    
                    with st.form("label_generation_form"):
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            # Number of labels
                            num_labels = st.number_input(
                            "Number of Labels to Generate",
                            min_value=1,
                            max_value=500,
                            value=10
                        )
                            
                            # Start label number
                            start_label_number = st.number_input(
                                "Start label number at",
                                min_value=1,
                                value=1,
                                help="The starting number for label numbering (e.g., if 1-10 already exist, start at 11)"
                            )
                            
                            # Initiation date
                            initiation_date = st.date_input(
                                "Date of Initiation",
                                value=date.today()
                            )
                            
                            # Number of explants
                            num_explants = st.number_input(
                                "Number of Explants",
                                min_value=1,
                                value=1
                            )
                        
                        with col2:
                            # Stage selection
                            available_stages = [
                                "Initiation",
                                "Multiplication",
                                "Elongation",
                                "Rooting",
                                "Acclimation",
                                "Hardening",
                                "Stock Plant",
                                "Mother Plant"
                            ]
                            
                            selected_stages = st.multiselect(
                                "Stage(s)",
                                options=available_stages,
                                default=["Initiation"]
                            )
                            
                            # Custom stage option
                            custom_stage = st.text_input("Custom Stage (optional)")
                        
                        # Pathogen status
                        st.write("**Pathogen Status**")
                        
                        if detected_pathogens:
                            st.warning(f"Detected pathogens in order batches: {', '.join(detected_pathogens)}")
                            include_detected = st.checkbox("Include detected pathogens on label", value=True)
                        else:
                            include_detected = False
                            st.success("No pathogens detected in order batches")
                        
                        # Manual pathogen entry
                        manual_pathogens = st.text_input(
                            "Additional Pathogens (comma-separated)",
                            placeholder="e.g., Bacterial contamination, Fungal infection"
                        )
                        
                        # Label customization
                        st.divider()
                        st.write("**Label Content Options**")
                        
                        col_content1, col_content2 = st.columns(2)
                        with col_content1:
                            include_cultivar = st.checkbox("Include Cultivar Name", value=True)
                            include_client = st.checkbox("Include Client Name", value=True)
                            include_order_date = st.checkbox("Include Order Date", value=True)
                            include_init_date = st.checkbox("Include Initiation Date", value=True)
                        with col_content2:
                            include_stages = st.checkbox("Include Stages", value=True)
                            include_explants = st.checkbox("Include Number of Explants", value=True)
                            include_pathogens = st.checkbox("Include Pathogen Status", value=True)
                        
                        st.divider()
                        st.write("**Label Code Options**")
                        
                        code_type = st.radio(
                            "Code Type",
                            options=["QR Code", "Barcode"],
                            index=0,
                            help="Choose between QR code (stores full data) or Barcode (stores UUID only)"
                        )
                        
                        if not BARCODE_AVAILABLE and code_type == "Barcode":
                            st.warning("Barcode library not available. Install with: pip install python-barcode[images]")
                            code_type = "QR Code"  # Fallback to QR code
                        
                        st.divider()
                        st.write("**Label Layout Options**")
                        
                        col3, col4, col5 = st.columns(3)
                        with col3:
                            label_width = st.number_input("Label Width (inches)", min_value=1.0, max_value=4.0, value=2.0, step=0.25)
                        with col4:
                            label_height = st.number_input("Label Height (inches)", min_value=0.5, max_value=3.0, value=1.0, step=0.25)
                        with col5:
                            labels_per_row = st.number_input("Labels per Row", min_value=1, max_value=5, value=3)
                        
                        # Notes
                        label_notes = st.text_area("Notes (optional)")
                        
                        submitted = st.form_submit_button("Generate Labels", type="primary", use_container_width=True)
                        
                        if submitted:
                            if not selected_stages and not custom_stage:
                                st.error("Please select at least one stage or enter a custom stage")
                            else:
                                # Compile stages
                                all_stages = selected_stages.copy()
                                if custom_stage:
                                    all_stages.append(custom_stage)
                                stages_str = ", ".join(all_stages)
                                
                                # Compile pathogen status
                                pathogens_list = []
                                if include_detected and detected_pathogens:
                                    pathogens_list.extend(detected_pathogens)
                                if manual_pathogens:
                                    pathogens_list.extend([p.strip() for p in manual_pathogens.split(",")])
                                pathogen_status = ", ".join(pathogens_list) if pathogens_list else None
                                
                                # Generate unique UUID for this label batch
                                label_uuid = str(uuid.uuid4())
                                
                                # Save to database
                                label_id = add_label(
                                    order_id=order_id,
                                    label_uuid=label_uuid,
                                    client_name=order['client_name'],
                                    cultivar=order['cultivar'],
                                    order_date=str(order['order_date']),
                                    initiation_date=str(initiation_date),
                                    stages=stages_str,
                                    pathogen_status=pathogen_status,
                                    num_labels=num_labels,
                                    notes=label_notes
                                )
                                
                                # Generate label data for PDF
                                labels_data = []
                                for i in range(num_labels):
                                    label_number = start_label_number + i
                                    # Append number suffix to cultivar name
                                    numbered_cultivar = f"{order['cultivar']} - {label_number}"
                                    labels_data.append({
                                        'uuid': label_uuid,
                                        'client_name': order['client_name'],
                                        'cultivar': numbered_cultivar,
                                        'order_date': str(order['order_date']),
                                        'initiation_date': str(initiation_date),
                                        'stages': stages_str,
                                        'pathogen_status': pathogen_status,
                                        'num_explants': num_explants,
                                        'include_cultivar': include_cultivar,
                                        'include_client': include_client,
                                        'include_order_date': include_order_date,
                                        'include_init_date': include_init_date,
                                    'include_stages': include_stages,
                                    'include_explants': include_explants,
                                    'include_pathogens': include_pathogens,
                                    'code_type': code_type
                                })
                                
                                # Calculate labels per column based on page size
                                labels_per_col = int(10 / label_height)
                                
                                # Generate PDF
                                pdf_buffer = generate_label_pdf(
                                    labels_data,
                                    label_size=(label_width, label_height),
                                    labels_per_row=labels_per_row,
                                    labels_per_col=labels_per_col
                                )
                                
                                # Store PDF data in session state for download outside form
                                st.session_state['label_pdf_buffer'] = pdf_buffer
                                st.session_state['label_pdf_filename'] = f"labels_order_{order_id}_{label_uuid[:8]}.pdf"
                                st.session_state['label_csv_filename'] = f"labels_order_{order_id}_{label_uuid[:8]}.csv"
                                st.session_state['labels_data'] = labels_data  # Store for CSV generation
                                st.session_state['label_preview_data'] = {
                                    'uuid': label_uuid,
                                    'client': order['client_name'],
                                    'cultivar': order['cultivar'],
                                    'order_date': str(order['order_date']),
                                    'init_date': str(initiation_date),
                                    'stages': stages_str,
                                    'pathogens': pathogen_status
                                }
                                
                                st.success(f"Generated {num_labels} labels (Label Batch ID: {label_id})")
                                st.rerun()
                    
                    # Display download buttons and preview outside the form
                    if 'label_pdf_buffer' in st.session_state and st.session_state['label_pdf_buffer']:
                        st.divider()
                        
                        # Download buttons in columns
                        col_dl1, col_dl2 = st.columns(2)
                        
                        with col_dl1:
                            st.download_button(
                                label="Download Labels PDF",
                                data=st.session_state['label_pdf_buffer'],
                                file_name=st.session_state['label_pdf_filename'],
                                mime="application/pdf",
                                type="primary",
                                use_container_width=True
                            )
                        
                        with col_dl2:
                            # Generate CSV from labels_data
                            if 'labels_data' in st.session_state and st.session_state['labels_data']:
                                labels_df = pd.DataFrame(st.session_state['labels_data'])
                                # Select relevant columns for CSV
                                csv_columns = ['cultivar', 'client_name', 'order_date', 'initiation_date', 
                                             'stages', 'num_explants', 'pathogen_status', 'uuid']
                                # Only include columns that exist
                                available_columns = [col for col in csv_columns if col in labels_df.columns]
                                csv_df = labels_df[available_columns]
                                
                                # Convert to CSV
                                csv_buffer = csv_df.to_csv(index=False)
                                
                                st.download_button(
                                    label="Download Labels CSV",
                                    data=csv_buffer,
                                    file_name=st.session_state['label_csv_filename'],
                                    mime="text/csv",
                                    type="secondary",
                                    use_container_width=True
                                )
                        
                        # Show preview of QR code data
                        if 'label_preview_data' in st.session_state:
                            with st.expander("Preview QR Code Data"):
                                st.json(st.session_state['label_preview_data'])
                else:
                    st.warning("No orders found for the selected cultivar.")
        else:
            st.info("No active orders available. Please create an order first.")
    
    with tab2:
        st.subheader("Generated Labels History")
        
        labels = get_labels()
        
        if not labels.empty:
            # Filter options
            col1, col2 = st.columns(2)
            with col1:
                client_filter = st.selectbox(
                    "Filter by Client",
                    ["All"] + labels['client_name'].unique().tolist(),
                    key="label_client_filter"
                )
            with col2:
                cultivar_filter = st.selectbox(
                    "Filter by Cultivar",
                    ["All"] + labels['cultivar'].unique().tolist(),
                    key="label_cultivar_filter"
                )
            
            filtered_labels = labels.copy()
            if client_filter != "All":
                filtered_labels = filtered_labels[filtered_labels['client_name'] == client_filter]
            if cultivar_filter != "All":
                filtered_labels = filtered_labels[filtered_labels['cultivar'] == cultivar_filter]
            
            # Display labels table
            display_cols = ['id', 'order_id', 'client_name', 'cultivar', 'initiation_date', 'stages', 'pathogen_status', 'num_labels', 'created_at']
            available_cols = [col for col in display_cols if col in filtered_labels.columns]
            st.dataframe(filtered_labels[available_cols], use_container_width=True, hide_index=True)
            
            # Reprint functionality
            st.divider()
            st.subheader("Reprint Labels")
            
            label_options = {
                f"#{row['id']} - {row['client_name']} - {row['cultivar']} ({row['num_labels']} labels)": row['id']
                for _, row in filtered_labels.iterrows()
            }
            
            selected_label_str = st.selectbox(
                "Select Label Batch to Reprint",
                options=list(label_options.keys())
            )
            
            if selected_label_str:
                label_id = label_options[selected_label_str]
                label_row = filtered_labels[filtered_labels['id'] == label_id].iloc[0]
                
                col1, col2 = st.columns(2)
                with col1:
                    reprint_count = st.number_input(
                        "Number of Labels to Reprint",
                        min_value=1,
                        max_value=500,
                        value=int(label_row['num_labels'])
                    )
                
                if st.button("Reprint Labels", type="secondary"):
                    # Generate label data for PDF
                    labels_data = []
                    for i in range(reprint_count):
                        labels_data.append({
                            'uuid': label_row['label_uuid'],
                            'client_name': label_row['client_name'],
                            'cultivar': label_row['cultivar'],
                            'order_date': label_row['order_date'],
                            'initiation_date': label_row['initiation_date'],
                            'stages': label_row['stages'],
                            'pathogen_status': label_row['pathogen_status'],
                            'num_explants': label_row.get('num_explants', None),  # May not exist for old labels
                            # Include flags default to True for reprints (show everything)
                            'include_cultivar': True,
                            'include_client': True,
                            'include_order_date': True,
                            'include_init_date': True,
                            'include_stages': True,
                            'include_explants': True,
                            'include_pathogens': True
                        })
                    
                    # Generate PDF with default layout
                    pdf_buffer = generate_label_pdf(labels_data)
                    
                    st.download_button(
                        label="Download Reprinted Labels PDF",
                        data=pdf_buffer,
                        file_name=f"labels_reprint_{label_id}.pdf",
                        mime="application/pdf"
                    )
            
            # Delete labels
            st.divider()
            st.subheader("Delete Label Batch")
            
            delete_label_str = st.selectbox(
                "Select Label Batch to Delete",
                options=list(label_options.keys()),
                key="delete_label_select"
            )
            
            if delete_label_str:
                delete_label_id = label_options[delete_label_str]
                st.warning("This action cannot be undone.")
                
                if st.button("Delete Label Batch", type="primary"):
                    delete_label(delete_label_id)
                    st.success(f"Label batch #{delete_label_id} deleted successfully!")
                    st.rerun()
        else:
            st.info("No labels generated yet")
    
    with tab3:
        st.subheader("QR Code Scanner / Lookup")
        
        st.write("Enter the UUID from a scanned QR code to retrieve label information:")
        
        lookup_uuid = st.text_input("Label UUID", placeholder="e.g., 550e8400-e29b-41d4-a716-446655440000")
        
        if st.button("Lookup Label", type="primary"):
            if lookup_uuid:
                label_info = get_label_by_uuid(lookup_uuid.strip())
                
                if label_info:
                    st.success("Label found!")
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write("**Order Information**")
                        st.write(f"- **Client:** {label_info['client_name']}")
                        st.write(f"- **Cultivar:** {label_info['cultivar']}")
                        st.write(f"- **Order Date:** {label_info['order_date']}")
                        st.write(f"- **Order ID:** {label_info['order_id']}")
                    
                    with col2:
                        st.write("**Label Information**")
                        st.write(f"- **Initiation Date:** {label_info['initiation_date']}")
                        st.write(f"- **Stage(s):** {label_info['stages']}")
                        if label_info['pathogen_status']:
                            st.write(f"- **Pathogen Status:** Pathogens: {label_info['pathogen_status']}")
                        else:
                            st.write("- **Pathogen Status:** Pathogens: none")
                        st.write(f"- **Labels Generated:** {label_info['num_labels']}")
                    
                    if label_info['notes']:
                        st.write(f"**Notes:** {label_info['notes']}")
                    
                    # Show associated order details
                    st.divider()
                    st.write("**Full Order Details**")
                    orders = get_orders()
                    order = orders[orders['id'] == label_info['order_id']]
                    if not order.empty:
                        st.dataframe(order, use_container_width=True, hide_index=True)
                else:
                    st.error("❌ No label found with this UUID")
            else:
                st.warning("Please enter a UUID to lookup")
        
        # Alternative: Paste full QR data
        st.divider()
        st.write("**Or paste the full QR code JSON data:**")
        
        qr_json = st.text_area("QR Code JSON Data", placeholder='{"uuid": "...", "client": "...", ...}')
        
        if st.button("Parse QR Data", type="secondary"):
            if qr_json:
                try:
                    data = json.loads(qr_json)
                    st.success("QR Data parsed successfully!")
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write("**Client Information**")
                        st.write(f"- **Client:** {data.get('client', 'N/A')}")
                        st.write(f"- **Cultivar:** {data.get('cultivar', 'N/A')}")
                        st.write(f"- **Order Date:** {data.get('order_date', 'N/A')}")
                    
                    with col2:
                        st.write("**Label Information**")
                        st.write(f"- **Initiation Date:** {data.get('init_date', 'N/A')}")
                        st.write(f"- **Stage(s):** {data.get('stages', 'N/A')}")
                        pathogens = data.get('pathogens')
                        if pathogens:
                            st.write(f"- **Pathogen Status:** Pathogens: {pathogens}")
                        else:
                            st.write("- **Pathogen Status:** Pathogens: none")
                    
                    # Lookup full database record
                    if 'uuid' in data:
                        label_info = get_label_by_uuid(data['uuid'])
                        if label_info:
                            st.info(f"Database record found - Label Batch ID: {label_info['id']}, Order ID: {label_info['order_id']}")
                
                except json.JSONDecodeError:
                    st.error("❌ Invalid JSON format")
            else:
                st.warning("Please enter QR code data to parse")

# Timeline
elif page == "Timeline":
    st.header("Complete Timeline View")
    
    tab1, tab2 = st.tabs(["Gantt Chart by Cultivar", "Batch Timeline"])
    
    with tab1:
        st.subheader("Gantt Chart - Cultivar Timeline")
        
        # Get all data
        orders = get_orders()
        batches = get_explant_batches()
        transfers = get_transfer_records()
        rooting_records = get_rooting_records()
        delivery_records = get_delivery_records()
        
        if not batches.empty and not orders.empty:
            # Merge batches with orders to get cultivar info
            batches_with_orders = batches.merge(orders, left_on='order_id', right_on='id', how='left', suffixes=('', '_order'))
            batches_with_orders = batches_with_orders[batches_with_orders['cultivar'].notna()]
            
            if not batches_with_orders.empty:
                # Get unique cultivars
                all_cultivars = batches_with_orders['cultivar'].unique().tolist()
                
                # Cultivar selection
                selected_cultivars = st.multiselect(
                    "Select Cultivars (leave empty for all)",
                    all_cultivars,
                    default=all_cultivars
                )
                
                if not selected_cultivars:
                    selected_cultivars = all_cultivars
                
                # Filter batches by selected cultivars
                filtered_batches = batches_with_orders[batches_with_orders['cultivar'].isin(selected_cultivars)]
                
                # Convert rooting_records batch_id to numeric once before the loop
                if not rooting_records.empty:
                    rooting_records = rooting_records.copy()
                    rooting_records['batch_id'] = pd.to_numeric(rooting_records['batch_id'], errors='coerce')
                
                # Build Gantt chart data
                gantt_data = []
                
                for _, batch in filtered_batches.iterrows():
                    cultivar = batch['cultivar']
                    batch_id = int(batch['id'])
                    
                    # Order received
                    order_date = pd.to_datetime(batch['order_date'])
                    
                    # Initiation
                    init_date = pd.to_datetime(batch['initiation_date'])
                    
                    # Get transfers for this batch
                    batch_transfers = transfers[transfers['batch_id'] == batch_id] if not transfers.empty else pd.DataFrame()
                    
                    # Get rooting records for this batch
                    batch_rooting = rooting_records[rooting_records['batch_id'] == batch_id] if not rooting_records.empty else pd.DataFrame()
                    
                    # Get delivery records for this batch
                    batch_deliveries = delivery_records[delivery_records['batch_id'] == batch_id] if not delivery_records.empty else pd.DataFrame()
                    
                    # Get order completion date
                    order_id = batch.get('order_id')
                    order_completion = None
                    if pd.notna(order_id):
                        order_row = orders[orders['id'] == int(order_id)]
                        if not order_row.empty and order_row.iloc[0].get('completed', 0) == 1:
                            completion_date = order_row.iloc[0].get('completion_date')
                            if pd.notna(completion_date):
                                order_completion = pd.to_datetime(completion_date)
                    
                    # Order received - single day marker
                    gantt_data.append({
                        'Cultivar': cultivar,
                        'Task': 'Order Received',
                        'Start': order_date,
                        'Finish': order_date + pd.Timedelta(days=1),
                        'Duration': 1
                    })
                    
                    # Passive time: Order to Initiation
                    if init_date > order_date + pd.Timedelta(days=1):
                        gantt_data.append({
                            'Cultivar': cultivar,
                            'Task': 'Passive Time',
                            'Start': order_date + pd.Timedelta(days=1),
                            'Finish': init_date,
                            'Duration': (init_date - (order_date + pd.Timedelta(days=1))).days
                        })
                    
                    # Initiation - single day marker
                    init_end = init_date + pd.Timedelta(days=1)
                    gantt_data.append({
                        'Cultivar': cultivar,
                        'Task': 'Explant Initiation',
                        'Start': init_date,
                        'Finish': init_end,
                        'Duration': 1
                    })
                    
                    # Initiation to First Transfer
                    if not batch_transfers.empty:
                        first_transfer = batch_transfers.sort_values('transfer_date').iloc[0]
                        first_transfer_date = pd.to_datetime(first_transfer['transfer_date'])
                        
                        # Passive time: Initiation to First Transfer
                        if first_transfer_date > init_end:
                            gantt_data.append({
                                'Cultivar': cultivar,
                                'Task': 'Passive Time',
                                'Start': init_end,
                                'Finish': first_transfer_date,
                                'Duration': (first_transfer_date - init_end).days
                            })
                        
                        # Show each individual transfer as a separate task
                        sorted_transfers = batch_transfers.sort_values('transfer_date')
                        prev_date = init_end  # Start from day after initiation
                        
                        for idx, transfer in sorted_transfers.iterrows():
                            transfer_date = pd.to_datetime(transfer['transfer_date'])
                            media_type = transfer['new_media']
                            explants_in = int(transfer['explants_in'])
                            explants_out = int(transfer['explants_out'])
                            multiplication = "Yes" if transfer['multiplication_occurred'] else "No"
                            
                            # Add passive time between previous event and this transfer
                            if transfer_date > prev_date + pd.Timedelta(days=1):
                                gantt_data.append({
                                    'Cultivar': cultivar,
                                    'Task': 'Passive Time',
                                    'Start': prev_date,
                                    'Finish': transfer_date,
                                    'Duration': (transfer_date - prev_date).days
                                })
                            
                            # Each transfer is shown as a point in time (1 day duration to make it visible)
                            gantt_data.append({
                                'Cultivar': cultivar,
                                'Task': f"Transfer #{transfer['id']}: {media_type} ({explants_in}→{explants_out}, Mult: {multiplication})",
                                'Start': transfer_date,
                                'Finish': transfer_date + pd.Timedelta(days=1),
                                'Duration': 1
                            })
                            
                            prev_date = transfer_date + pd.Timedelta(days=1)
                        
                        # Show rooting media placement dates
                        if not batch_rooting.empty:
                            sorted_rooting = batch_rooting.sort_values('placement_date')
                            for idx, rooting in sorted_rooting.iterrows():
                                placement_date = pd.to_datetime(rooting['placement_date'])
                                num_placed = int(rooting['num_placed'])
                                
                                # Add passive time if there's a gap before placement
                                if placement_date > prev_date + pd.Timedelta(days=1):
                                    gantt_data.append({
                                        'Cultivar': cultivar,
                                        'Task': 'Passive Time',
                                        'Start': prev_date,
                                        'Finish': placement_date,
                                        'Duration': (placement_date - prev_date).days
                                    })
                                
                                # Rooting placement as a point in time
                                gantt_data.append({
                                    'Cultivar': cultivar,
                                    'Task': f"Rooting Placement: {num_placed} placed",
                                    'Start': placement_date,
                                    'Finish': placement_date + pd.Timedelta(days=1),
                                    'Duration': 1
                                })
                                
                                prev_date = placement_date + pd.Timedelta(days=1)
                                
                                # Rooting completion date if available
                                if pd.notna(rooting['rooting_date']):
                                    rooting_date = pd.to_datetime(rooting['rooting_date'])
                                    num_rooted = int(rooting['num_rooted']) if pd.notna(rooting['num_rooted']) else 0
                                    
                                    # Add passive time if there's a gap before completion
                                    if rooting_date > prev_date + pd.Timedelta(days=1):
                                        gantt_data.append({
                                            'Cultivar': cultivar,
                                            'Task': 'Passive Time',
                                            'Start': prev_date,
                                            'Finish': rooting_date,
                                            'Duration': (rooting_date - prev_date).days
                                        })
                                    
                                    # Show rooting completion as a point in time
                                    gantt_data.append({
                                        'Cultivar': cultivar,
                                        'Task': f"Rooting Complete: {num_rooted} rooted",
                                        'Start': rooting_date,
                                        'Finish': rooting_date + pd.Timedelta(days=1),
                                        'Duration': 1
                                    })
                                    
                                    prev_date = rooting_date + pd.Timedelta(days=1)
                    
                    # Add delivery events
                    if not batch_deliveries.empty:
                        sorted_deliveries = batch_deliveries.sort_values('delivery_date')
                        for idx, delivery in sorted_deliveries.iterrows():
                            delivery_date = pd.to_datetime(delivery['delivery_date'])
                            num_delivered = int(delivery['num_delivered'])
                            
                            # Add passive time if there's a gap before delivery
                            if delivery_date > prev_date + pd.Timedelta(days=1):
                                gantt_data.append({
                                    'Cultivar': cultivar,
                                    'Task': 'Passive Time',
                                    'Start': prev_date,
                                    'Finish': delivery_date,
                                    'Duration': (delivery_date - prev_date).days
                                })
                            
                            # Delivery as a point in time
                            gantt_data.append({
                                'Cultivar': cultivar,
                                'Task': f"Delivery: {num_delivered} delivered",
                                'Start': delivery_date,
                                'Finish': delivery_date + pd.Timedelta(days=1),
                                'Duration': 1
                            })
                            
                            prev_date = delivery_date + pd.Timedelta(days=1)
                    
                    # Add order completion event
                    if order_completion is not None:
                        # Add passive time if there's a gap before completion
                        if order_completion > prev_date + pd.Timedelta(days=1):
                            gantt_data.append({
                                'Cultivar': cultivar,
                                'Task': 'Passive Time',
                                'Start': prev_date,
                                'Finish': order_completion,
                                'Duration': (order_completion - prev_date).days
                            })
                        
                        # Order completion as a point in time
                        gantt_data.append({
                            'Cultivar': cultivar,
                            'Task': 'Order Completed',
                            'Start': order_completion,
                            'Finish': order_completion + pd.Timedelta(days=1),
                            'Duration': 1
                        })
                else:
                    # No transfers yet, show passive time from initiation to today
                    today = pd.to_datetime(date.today())
                    if today > init_date + pd.Timedelta(days=1):
                        gantt_data.append({
                            'Cultivar': cultivar,
                            'Task': 'Passive Time',
                            'Start': init_date + pd.Timedelta(days=1),
                            'Finish': today,
                            'Duration': (today - init_date - pd.Timedelta(days=1)).days
                        })
                
                if gantt_data:
                    gantt_df = pd.DataFrame(gantt_data)
                    
                    # Create Gantt chart
                    fig = px.timeline(
                        gantt_df,
                        x_start='Start',
                        x_end='Finish',
                        y='Cultivar',
                        color='Task',
                        title='Cultivar Timeline - Gantt Chart',
                        labels={'Start': 'Start Date', 'Finish': 'End Date', 'Cultivar': 'Cultivar'},
                        hover_data=['Duration']
                    )
                    
                    fig.update_yaxes(autorange="reversed")
                    fig.update_layout(
                        height=max(400, len(selected_cultivars) * 50),
                        xaxis_title="Date",
                        yaxis_title="Cultivar",
                        showlegend=True
                    )
                    
                    # Configure for high-resolution PNG downloads
                    config = {
                        'toImageButtonOptions': {
                            'format': 'png',
                            'filename': 'timeline_chart',
                            'height': None,  # Use chart height
                            'width': None,   # Use chart width
                            'scale': 3       # 3x scale for high resolution (default is 1)
                        }
                    }
                    
                    st.plotly_chart(fig, use_container_width=True, config=config)
                    
                    # Summary table
                    st.subheader("Summary by Cultivar")
                    summary_data = []
                    for cultivar in selected_cultivars:
                        cultivar_data = gantt_df[gantt_df['Cultivar'] == cultivar]
                        if not cultivar_data.empty:
                            total_days = cultivar_data['Duration'].sum()
                            summary_data.append({
                                'Cultivar': cultivar,
                                'Total Days': int(total_days),
                                'Stages': len(cultivar_data),
                                'Current Stage': cultivar_data.iloc[-1]['Task'] if not cultivar_data.empty else 'N/A'
                            })
                    
                    if summary_data:
                        summary_df = pd.DataFrame(summary_data)
                        st.dataframe(summary_df, use_container_width=True, hide_index=True)
                else:
                    st.info("No timeline data available for selected cultivars")
            else:
                st.info("No batches linked to orders with cultivar information")
        else:
            st.info("No data available for Gantt chart")
    
    with tab2:
        st.subheader("Batch Timeline (Detailed View)")
        
        batches = get_explant_batches()
        
        if not batches.empty:
            # Filter by batch
            batch_options = {f"{row['batch_name']} (ID: {row['id']})": row['id'] 
                            for _, row in batches.iterrows()}
            selected_batch = st.selectbox("Select Batch", list(batch_options.keys()))
            batch_id = batch_options[selected_batch]
            
            batch_info = batches[batches['id'] == batch_id].iloc[0]
            
            # Get order info if linked
            order_info = None
            if pd.notna(batch_info.get('order_id')):
                orders = get_orders()
                order_info = orders[orders['id'] == batch_info['order_id']].iloc[0] if not orders.empty else None
            
            # Get all related data
            infections = get_infection_records(batch_id)
            transfers = get_transfer_records(batch_id)
            rooting_records = get_rooting_records(batch_id)
            
            # Display timeline
            st.subheader(f"Timeline for Batch: {batch_info['batch_name']}")
            
            timeline_items = []
            
            # Order receipt (if linked)
            if order_info is not None:
                timeline_items.append({
                    'date': pd.to_datetime(order_info['order_date']),
                    'event': 'Order Received',
                    'details': f"Client: {order_info['client_name']}, Cultivar: {order_info['cultivar']}, {order_info['num_plants']} plants"
                })
            
            # Initiation
            timeline_items.append({
                'date': pd.to_datetime(batch_info['initiation_date']),
                'event': 'Explant Initiation',
                'details': f"{batch_info['num_explants']} explants, Type: {batch_info['explant_type']}, Media: {batch_info['media_type']}"
            })
            
            # Infections
            for _, infection in infections.iterrows():
                timeline_items.append({
                    'date': pd.to_datetime(infection['identification_date']),
                    'event': 'Infection Identified',
                    'details': f"{infection['num_infected']} explants, Type: {infection['infection_type']}"
                })
            
            # Transfers
            for _, transfer in transfers.iterrows():
                timeline_items.append({
                    'date': pd.to_datetime(transfer['transfer_date']),
                    'event': 'Transfer',
                    'details': f"{transfer['explants_in']} in → {transfer['explants_out']} out, Media: {transfer['new_media']}, Multiplication: {'Yes' if transfer['multiplication_occurred'] else 'No'}"
                })
            
            # Rooting
            for _, rooting in rooting_records.iterrows():
                timeline_items.append({
                    'date': pd.to_datetime(rooting['placement_date']),
                    'event': 'Placed in Rooting Media',
                    'details': f"{rooting['num_placed']} explants placed"
                })
                if pd.notna(rooting['rooting_date']):
                    timeline_items.append({
                        'date': pd.to_datetime(rooting['rooting_date']),
                        'event': 'Rooting Completed',
                        'details': f"{rooting['num_rooted']} explants rooted ({rooting['num_rooted']/rooting['num_placed']*100:.1f}%)"
                    })
            
            # Deliveries
            delivery_records = get_delivery_records()
            batch_deliveries = delivery_records[delivery_records['batch_id'] == batch_id] if not delivery_records.empty else pd.DataFrame()
            for _, delivery in batch_deliveries.iterrows():
                timeline_items.append({
                    'date': pd.to_datetime(delivery['delivery_date']),
                    'event': 'Delivery',
                    'details': f"{delivery['num_delivered']} plants delivered" + (f" ({delivery['delivery_method']})" if pd.notna(delivery.get('delivery_method')) else "")
                })
            
            # Order completion
            if order_info is not None:
                if order_info.get('completed', 0) == 1 and pd.notna(order_info.get('completion_date')):
                    timeline_items.append({
                        'date': pd.to_datetime(order_info['completion_date']),
                        'event': 'Order Completed',
                        'details': f"Order marked as complete"
                    })
            
            # Sort by date
            timeline_df = pd.DataFrame(timeline_items)
            if not timeline_df.empty:
                timeline_df = timeline_df.sort_values('date')
                timeline_df['date'] = timeline_df['date'].dt.strftime('%Y-%m-%d')
                
                st.dataframe(timeline_df, use_container_width=True, hide_index=True)
            else:
                st.info("No timeline data available")
        else:
            st.info("No batches available")

# Statistics
elif page == "Statistics":
    st.header("Statistics & Analytics")
    
    # Toggle to include/exclude archived orders
    include_archived = st.checkbox("Include Archived Orders", value=False)
    
    tab1, tab2 = st.tabs(["Global Statistics", "Per-Cultivar Statistics"])
    
    with tab1:
        st.subheader("Global Statistics")
        
        conn = get_connection()
        
        # Get all data
        orders = get_orders()
        batches = get_explant_batches()
        infections = get_infection_records()
        transfers = get_transfer_records()
        rooting_records = get_rooting_records()
        
        # Filter out archived orders if toggle is off
        if not include_archived:
            if 'completed' in orders.columns:
                active_order_ids = orders[orders.get('completed', 0) == 0]['id'].tolist()
                # Filter batches to only those linked to active orders
                if not batches.empty:
                    batches = batches[batches['order_id'].isin(active_order_ids) | batches['order_id'].isna()]
                # Filter infections, transfers, and rooting records based on active batches
                if not batches.empty:
                    active_batch_ids = batches['id'].tolist()
                    if not infections.empty:
                        infections = infections[infections['batch_id'].isin(active_batch_ids)]
                    if not transfers.empty:
                        transfers = transfers[transfers['batch_id'].isin(active_batch_ids)]
                    if not rooting_records.empty:
                        rooting_records = rooting_records[rooting_records['batch_id'].isin(active_batch_ids)]
        
        if not batches.empty:
            col1, col2, col3, col4 = st.columns(4)
            
            # Rooting rate
            total_placed = rooting_records['num_placed'].sum() if not rooting_records.empty else 0
            # Handle NaN values in num_rooted before summing
            if not rooting_records.empty and 'num_rooted' in rooting_records.columns:
                total_rooted = rooting_records['num_rooted'].fillna(0).sum()
            else:
                total_rooted = 0
            rooting_rate = (total_rooted / total_placed * 100) if total_placed > 0 else 0
            
            with col1:
                st.metric("Global Rooting Rate", f"{rooting_rate:.1f}%")
            
            # Infection rate
            total_explants = batches['num_explants'].sum()
            total_infected = infections['num_infected'].sum() if not infections.empty else 0
            infection_rate = (total_infected / total_explants * 100) if total_explants > 0 else 0
            
            with col2:
                st.metric("Global Infection Rate", f"{infection_rate:.1f}%")
            
            # Average time calculations
            if not batches.empty and not transfers.empty:
                # Calculate average time from initiation to first transfer
                batch_transfer_times = []
                for _, batch in batches.iterrows():
                    batch_transfers = transfers[transfers['batch_id'] == batch['id']]
                    if not batch_transfers.empty:
                        first_transfer = batch_transfers.sort_values('transfer_date').iloc[0]
                        init_date = pd.to_datetime(batch['initiation_date'])
                        transfer_date = pd.to_datetime(first_transfer['transfer_date'])
                        days = (transfer_date - init_date).days
                        if days >= 0:
                            batch_transfer_times.append(days)
                
                avg_init_to_transfer = sum(batch_transfer_times) / len(batch_transfer_times) if batch_transfer_times else 0
                
                with col3:
                    st.metric("Avg Days: Initiation to First Transfer", f"{avg_init_to_transfer:.1f}")
                
                # Calculate average time in rooting
                if not rooting_records.empty:
                    rooting_times = []
                    for _, record in rooting_records.iterrows():
                        if pd.notna(record['rooting_date']) and pd.notna(record['placement_date']):
                            placement = pd.to_datetime(record['placement_date'])
                            rooting = pd.to_datetime(record['rooting_date'])
                            days = (rooting - placement).days
                            if days >= 0:
                                rooting_times.append(days)
                    
                    avg_rooting_time = sum(rooting_times) / len(rooting_times) if rooting_times else 0
                    
                    with col4:
                        st.metric("Avg Days in Rooting Media", f"{avg_rooting_time:.1f}")
                else:
                    with col4:
                        st.metric("Avg Days in Rooting Media", "N/A")
            else:
                with col3:
                    st.metric("Avg Days: Initiation to First Transfer", "N/A")
                with col4:
                    st.metric("Avg Days in Rooting Media", "N/A")
            
            st.divider()
            
            # Total Explants Over Time
            st.subheader("Total Explants Over Time")
            if not batches.empty:
                # Get all events that affect explant count
                events = []
                
                # Batch initiations (add explants)
                for _, batch in batches.iterrows():
                    events.append({
                        'date': pd.to_datetime(batch['initiation_date']),
                        'change': int(batch['num_explants']),
                        'type': 'initiation'
                    })
                
                # Infections (subtract explants)
                if not infections.empty:
                    for _, infection in infections.iterrows():
                        events.append({
                            'date': pd.to_datetime(infection['identification_date']),
                            'change': -int(infection['num_infected']),
                            'type': 'infection'
                        })
                
                # Transfers (net change: explants_out - explants_in)
                if not transfers.empty:
                    for _, transfer in transfers.iterrows():
                        net_change = int(transfer['explants_out']) - int(transfer['explants_in'])
                        events.append({
                            'date': pd.to_datetime(transfer['transfer_date']),
                            'change': net_change,
                            'type': 'transfer'
                        })
                
                if events:
                    # Sort events by date
                    events_df = pd.DataFrame(events)
                    events_df = events_df.sort_values('date')
                    
                    # Calculate cumulative total
                    events_df['cumulative_total'] = events_df['change'].cumsum()
                    
                    # Group by date (in case multiple events on same day)
                    daily_changes = events_df.groupby(events_df['date'].dt.date).agg({
                        'change': 'sum',
                        'cumulative_total': 'last'
                    }).reset_index()
                    daily_changes.columns = ['Date', 'Daily Change', 'Cumulative Total']
                    daily_changes['Date'] = pd.to_datetime(daily_changes['Date'])
                    daily_changes = daily_changes.sort_values('Date')
                    
                    # Recalculate cumulative after grouping
                    daily_changes['Cumulative Total'] = daily_changes['Daily Change'].cumsum()
                    
                    # Create continuous timeline
                    date_range = pd.date_range(
                        start=daily_changes['Date'].min(),
                        end=pd.to_datetime(date.today()),
                        freq='D'
                    )
                    
                    continuous_timeline = pd.DataFrame({'Date': date_range})
                    continuous_timeline = continuous_timeline.merge(
                        daily_changes[['Date', 'Cumulative Total']],
                        on='Date',
                        how='left'
                    )
                    continuous_timeline['Cumulative Total'] = continuous_timeline['Cumulative Total'].ffill().fillna(0)
                    continuous_timeline = continuous_timeline.set_index('Date')
                    
                    st.line_chart(continuous_timeline['Cumulative Total'])
                else:
                    st.info("No event data available")
            
            st.divider()
            
            # Charts
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Rooting Rate Over Time**")
                if not rooting_records.empty and 'rooting_date' in rooting_records.columns:
                    rooting_timeline = rooting_records[pd.notna(rooting_records['rooting_date'])].copy()
                    if not rooting_timeline.empty:
                        rooting_timeline['rooting_date'] = pd.to_datetime(rooting_timeline['rooting_date'])
                        daily_rooting = rooting_timeline.groupby(rooting_timeline['rooting_date'].dt.date).agg({
                            'num_rooted': 'sum',
                            'num_placed': 'sum'
                        }).reset_index()
                        daily_rooting['rate'] = (daily_rooting['num_rooted'] / daily_rooting['num_placed'] * 100).round(1)
                        daily_rooting['rooting_date'] = pd.to_datetime(daily_rooting['rooting_date'])
                        daily_rooting = daily_rooting.sort_values('rooting_date')
                        
                        # Calculate cumulative totals for rate calculation
                        daily_rooting['cumulative_rooted'] = daily_rooting['num_rooted'].cumsum()
                        daily_rooting['cumulative_placed'] = daily_rooting['num_placed'].cumsum()
                        daily_rooting['cumulative_rate'] = (daily_rooting['cumulative_rooted'] / daily_rooting['cumulative_placed'] * 100).round(1)
                        
                        # Create continuous timeline
                        date_range = pd.date_range(
                            start=daily_rooting['rooting_date'].min(),
                            end=pd.to_datetime(date.today()),
                            freq='D'
                        )
                        
                        continuous_timeline = pd.DataFrame({'Date': date_range})
                        continuous_timeline = continuous_timeline.merge(
                            daily_rooting[['rooting_date', 'cumulative_rate']],
                            left_on='Date',
                            right_on='rooting_date',
                            how='left'
                        )
                        continuous_timeline['cumulative_rate'] = continuous_timeline['cumulative_rate'].ffill()
                        continuous_timeline = continuous_timeline.set_index('Date')
                        
                        st.line_chart(continuous_timeline['cumulative_rate'])
                    else:
                        st.info("No rooting completion data")
                else:
                    st.info("No rooting data available")
            
            with col2:
                st.write("**Infection Rate Over Time**")
                if not infections.empty:
                    infection_timeline = infections.copy()
                    infection_timeline['identification_date'] = pd.to_datetime(infection_timeline['identification_date'])
                    daily_infections = infection_timeline.groupby(infection_timeline['identification_date'].dt.date).agg({
                        'num_infected': 'sum'
                    }).reset_index()
                    daily_infections['identification_date'] = pd.to_datetime(daily_infections['identification_date'])
                    daily_infections = daily_infections.sort_values('identification_date')
                    
                    # Calculate cumulative infection rate
                    # Get total explants initiated up to each date
                    batches_sorted = batches.copy()
                    batches_sorted['initiation_date'] = pd.to_datetime(batches_sorted['initiation_date'])
                    batches_sorted = batches_sorted.sort_values('initiation_date')
                    
                    daily_infections['cumulative_infected'] = daily_infections['num_infected'].cumsum()
                    
                    # Calculate total explants initiated by each infection date
                    infection_rates = []
                    for _, inf_row in daily_infections.iterrows():
                        inf_date = inf_row['identification_date']
                        total_initiated = batches_sorted[batches_sorted['initiation_date'] <= inf_date]['num_explants'].sum()
                        if total_initiated > 0:
                            rate = (inf_row['cumulative_infected'] / total_initiated * 100)
                            infection_rates.append({
                                'Date': inf_date,
                                'Infection Rate': rate
                            })
                    
                    if infection_rates:
                        rates_df = pd.DataFrame(infection_rates)
                        
                        # Create continuous timeline
                        date_range = pd.date_range(
                            start=rates_df['Date'].min(),
                            end=pd.to_datetime(date.today()),
                            freq='D'
                        )
                        
                        continuous_timeline = pd.DataFrame({'Date': date_range})
                        continuous_timeline = continuous_timeline.merge(
                            rates_df,
                            on='Date',
                            how='left'
                        )
                        continuous_timeline['Infection Rate'] = continuous_timeline['Infection Rate'].ffill()
                        continuous_timeline = continuous_timeline.set_index('Date')
                        
                        st.line_chart(continuous_timeline['Infection Rate'])
                    else:
                        st.info("No infection rate data available")
                else:
                    st.info("No infection data available")
        else:
            st.info("No data available for statistics")
        
        conn.close()
    
    with tab2:
        st.subheader("Per-Cultivar Statistics")
        
        orders = get_orders()
        batches = get_explant_batches()
        infections = get_infection_records()
        transfers = get_transfer_records()
        rooting_records = get_rooting_records()
        
        # Filter out archived orders if toggle is off
        if not include_archived:
            if 'completed' in orders.columns:
                active_order_ids = orders[orders.get('completed', 0) == 0]['id'].tolist()
                # Filter batches to only those linked to active orders
                if not batches.empty:
                    batches = batches[batches['order_id'].isin(active_order_ids) | batches['order_id'].isna()]
                # Filter infections, transfers, and rooting records based on active batches
                if not batches.empty:
                    active_batch_ids = batches['id'].tolist()
                    if not infections.empty:
                        infections = infections[infections['batch_id'].isin(active_batch_ids)]
                    if not transfers.empty:
                        transfers = transfers[transfers['batch_id'].isin(active_batch_ids)]
                    if not rooting_records.empty:
                        rooting_records = rooting_records[rooting_records['batch_id'].isin(active_batch_ids)]
        
        if not orders.empty and not batches.empty:
            # Merge orders and batches to get cultivar info
            batches_with_orders = batches.merge(orders, left_on='order_id', right_on='id', how='left', suffixes=('', '_order'))
            
            if not batches_with_orders.empty:
                cultivar_stats = []
                
                for cultivar in batches_with_orders['cultivar'].dropna().unique():
                    cultivar_batches = batches_with_orders[batches_with_orders['cultivar'] == cultivar]
                    cultivar_batch_ids = cultivar_batches['id'].tolist()
                    
                    # Get data for this cultivar
                    cultivar_infections = infections[infections['batch_id'].isin(cultivar_batch_ids)] if not infections.empty else pd.DataFrame()
                    cultivar_transfers = transfers[transfers['batch_id'].isin(cultivar_batch_ids)] if not transfers.empty else pd.DataFrame()
                    cultivar_rooting = rooting_records[rooting_records['batch_id'].isin(cultivar_batch_ids)] if not rooting_records.empty else pd.DataFrame()
                    
                    # Calculate statistics
                    total_explants = cultivar_batches['num_explants'].sum()
                    total_infected = cultivar_infections['num_infected'].sum() if not cultivar_infections.empty else 0
                    infection_rate = (total_infected / total_explants * 100) if total_explants > 0 else 0
                    
                    # Calculate total lost to contamination (use num_lost if available, otherwise num_infected for backward compatibility)
                    if not cultivar_infections.empty:
                        # Handle num_lost column - use it if available, otherwise fall back to num_infected
                        if 'num_lost' in cultivar_infections.columns:
                            # Check if num_lost has any non-null values
                            if cultivar_infections['num_lost'].notna().any():
                                total_lost = cultivar_infections['num_lost'].fillna(0).sum()
                            else:
                                # All values are null, fall back to num_infected for backward compatibility
                                total_lost = cultivar_infections['num_infected'].fillna(0).sum()
                        else:
                            # No num_lost column, use num_infected
                            total_lost = cultivar_infections['num_infected'].fillna(0).sum()
                    else:
                        total_lost = 0
                    loss_rate = (total_lost / total_explants * 100) if total_explants > 0 else 0
                    
                    total_placed = cultivar_rooting['num_placed'].sum() if not cultivar_rooting.empty else 0
                    # Handle NaN values in num_rooted before summing
                    if not cultivar_rooting.empty and 'num_rooted' in cultivar_rooting.columns:
                        total_rooted = cultivar_rooting['num_rooted'].fillna(0).sum()
                    else:
                        total_rooted = 0
                    rooting_rate = (total_rooted / total_placed * 100) if total_placed > 0 else 0
                    
                    # Average time in rooting
                    avg_rooting_time = 0
                    if not cultivar_rooting.empty:
                        rooting_times = []
                        for _, record in cultivar_rooting.iterrows():
                            if pd.notna(record['rooting_date']) and pd.notna(record['placement_date']):
                                placement = pd.to_datetime(record['placement_date'])
                                rooting = pd.to_datetime(record['rooting_date'])
                                days = (rooting - placement).days
                                if days >= 0:
                                    rooting_times.append(days)
                        avg_rooting_time = sum(rooting_times) / len(rooting_times) if rooting_times else 0
                    
                    cultivar_stats.append({
                        'Cultivar': cultivar,
                        'Total Explants': int(total_explants),
                        'Infection Rate (%)': f"{infection_rate:.1f}",
                        'Total Placed in Rooting': int(total_placed),
                        'Total Rooted': int(total_rooted) if pd.notna(total_rooted) else 0,
                        'Rooting Rate (%)': f"{rooting_rate:.1f}",
                        'Avg Days in Rooting': f"{avg_rooting_time:.1f}" if avg_rooting_time > 0 else "N/A",
                        'Total Lost': int(total_lost),
                        'Loss Rate (%)': loss_rate
                    })
                
                stats_df = pd.DataFrame(cultivar_stats)
                st.dataframe(stats_df, use_container_width=True, hide_index=True)
                
                # Pie charts for % of initiated explants lost to contamination by cultivar
                st.subheader("% of Initiated Explants Lost to Contamination by Cultivar")
                if not stats_df.empty:
                    # Create columns for pie charts (2 per row)
                    num_cultivars = len(stats_df)
                    cols_per_row = 2
                    num_rows = (num_cultivars + cols_per_row - 1) // cols_per_row
                    
                    for row_idx in range(num_rows):
                        cols = st.columns(cols_per_row)
                        for col_idx in range(cols_per_row):
                            cultivar_idx = row_idx * cols_per_row + col_idx
                            if cultivar_idx < num_cultivars:
                                cultivar_row = stats_df.iloc[cultivar_idx]
                                cultivar_name = cultivar_row['Cultivar']
                                total_explants = cultivar_row['Total Explants']
                                total_lost = cultivar_row['Total Lost']
                                loss_rate = cultivar_row['Loss Rate (%)']
                                
                                with cols[col_idx]:
                                    # Create pie chart data
                                    lost = total_lost
                                    remaining = total_explants - total_lost
                                    
                                    if total_explants > 0:
                                        fig = go.Figure(data=[go.Pie(
                                            labels=['Lost to Contamination', 'Remaining'],
                                            values=[lost, remaining],
                                            hole=0.4,
                                            marker_colors=['#ef4444', '#10b981'],
                                            textinfo='label+percent',
                                            texttemplate='%{label}<br>%{percent:.1f}%<br>(%{value})',
                                            hovertemplate='<b>%{label}</b><br>Count: %{value}<br>Percentage: %{percent:.1f}%<extra></extra>'
                                        )])
                                        fig.update_layout(
                                            title=f"{cultivar_name}<br><span style='font-size:0.8em'>Loss Rate: {loss_rate:.1f}%</span>",
                                            showlegend=True,
                                            height=350,
                                            margin=dict(t=80, b=20, l=20, r=20)
                                        )
                                        st.plotly_chart(fig, use_container_width=True)
                                    else:
                                        st.info(f"{cultivar_name}: No explants initiated")
                
                # Total Explants Over Time by Cultivar
                st.subheader("Total Explants Over Time by Cultivar")
                if not batches_with_orders.empty:
                    # Prepare data for multi-line chart
                    all_dates = []
                    cultivar_chart_data = {}
                    
                    for cultivar in batches_with_orders['cultivar'].dropna().unique():
                        cultivar_batches = batches_with_orders[batches_with_orders['cultivar'] == cultivar]
                        cultivar_batch_ids = cultivar_batches['id'].tolist()
                        
                        # Get cultivar-specific data
                        cultivar_infections = infections[infections['batch_id'].isin(cultivar_batch_ids)] if not infections.empty else pd.DataFrame()
                        cultivar_transfers = transfers[transfers['batch_id'].isin(cultivar_batch_ids)] if not transfers.empty else pd.DataFrame()
                        
                        # Get all events that affect explant count for this cultivar
                        events = []
                        
                        # Batch initiations
                        for _, batch in cultivar_batches.iterrows():
                            events.append({
                                'date': pd.to_datetime(batch['initiation_date']),
                                'change': int(batch['num_explants']),
                                'type': 'initiation'
                            })
                        
                        # Infections
                        if not cultivar_infections.empty:
                            for _, infection in cultivar_infections.iterrows():
                                events.append({
                                    'date': pd.to_datetime(infection['identification_date']),
                                    'change': -int(infection['num_infected']),
                                    'type': 'infection'
                                })
                        
                        # Transfers (net change)
                        if not cultivar_transfers.empty:
                            for _, transfer in cultivar_transfers.iterrows():
                                net_change = int(transfer['explants_out']) - int(transfer['explants_in'])
                                events.append({
                                    'date': pd.to_datetime(transfer['transfer_date']),
                                    'change': net_change,
                                    'type': 'transfer'
                                })
                        
                        if events:
                            events_df = pd.DataFrame(events)
                            events_df = events_df.sort_values('date')
                            events_df['cumulative_total'] = events_df['change'].cumsum()
                            
                            # Group by date
                            daily_changes = events_df.groupby(events_df['date'].dt.date).agg({
                                'change': 'sum',
                                'cumulative_total': 'last'
                            }).reset_index()
                            daily_changes.columns = ['Date', 'Daily Change', 'Cumulative Total']
                            daily_changes['Date'] = pd.to_datetime(daily_changes['Date'])
                            daily_changes = daily_changes.sort_values('Date')
                            daily_changes['Cumulative Total'] = daily_changes['Daily Change'].cumsum()
                            
                            cultivar_chart_data[cultivar] = daily_changes[['Date', 'Cumulative Total']]
                            all_dates.extend(daily_changes['Date'].tolist())
                    
                    if cultivar_chart_data and all_dates:
                        # Create continuous date range
                        date_range = pd.date_range(
                            start=min(all_dates),
                            end=pd.to_datetime(date.today()),
                            freq='D'
                        )
                        
                        chart_data = pd.DataFrame({'Date': date_range})
                        
                        # Add each cultivar's data
                        for cultivar_name, cultivar_data in cultivar_chart_data.items():
                            # Merge this cultivar's data
                            merged = chart_data.merge(
                                cultivar_data,
                                on='Date',
                                how='left'
                            )
                            # Forward fill and rename
                            merged['Cumulative Total'] = merged['Cumulative Total'].ffill().fillna(0)
                            chart_data[cultivar_name] = merged['Cumulative Total']
                        
                        # Set Date as index
                        chart_data = chart_data.set_index('Date')
                        st.line_chart(chart_data)
                    else:
                        st.info("No date data available")
            else:
                st.info("No batches linked to orders")
        else:
            st.info("No data available")

# Archive
elif page == "Archive":
    st.header("Archive - Completed Orders")
    
    orders = get_orders()
    completed_orders = orders[orders.get('completed', 0) == 1] if 'completed' in orders.columns else pd.DataFrame()
    
    if not completed_orders.empty:
        # Filter options
        col1, col2 = st.columns(2)
        with col1:
            client_filter = st.selectbox(
                "Filter by Client",
                ["All"] + completed_orders['client_name'].unique().tolist()
            )
        with col2:
            cultivar_filter = st.selectbox(
                "Filter by Cultivar",
                ["All"] + completed_orders['cultivar'].unique().tolist()
            )
        
        filtered_orders = completed_orders.copy()
        if client_filter != "All":
            filtered_orders = filtered_orders[filtered_orders['client_name'] == client_filter]
        if cultivar_filter != "All":
            filtered_orders = filtered_orders[filtered_orders['cultivar'] == cultivar_filter]
        
        # Format the display to show recurring status
        display_orders = filtered_orders.copy()
        if 'is_recurring' in display_orders.columns:
            display_orders['Recurring'] = display_orders['is_recurring'].apply(lambda x: 'Yes' if x == 1 else 'No')
        
        # Display orders
        display_cols = ['id', 'client_name', 'cultivar', 'num_plants', 'delivery_quantity', 'Recurring', 'plant_size', 'order_date', 'completion_date', 'notes']
        available_cols = [col for col in display_cols if col in display_orders.columns]
        st.dataframe(display_orders[available_cols], use_container_width=True, hide_index=True)
        
        # Summary statistics
        st.subheader("Archive Summary")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Completed Orders", len(completed_orders))
        with col2:
            total_plants = completed_orders['num_plants'].sum()
            st.metric("Total Plants Ordered", total_plants)
        with col3:
            if 'completion_date' in completed_orders.columns:
                avg_completion_days = None
                for _, order in completed_orders.iterrows():
                    if pd.notna(order.get('completion_date')) and pd.notna(order.get('order_date')):
                        order_date = pd.to_datetime(order['order_date'])
                        completion_date = pd.to_datetime(order['completion_date'])
                        days = (completion_date - order_date).days
                        if avg_completion_days is None:
                            avg_completion_days = days
                        else:
                            avg_completion_days = (avg_completion_days + days) / 2
                if avg_completion_days:
                    st.metric("Average Days to Complete", f"{avg_completion_days:.1f}")
                else:
                    st.metric("Average Days to Complete", "N/A")
            else:
                st.metric("Average Days to Complete", "N/A")
        
        # Get delivery records for completed orders
        delivery_records = get_delivery_records()
        if not delivery_records.empty:
            st.subheader("Delivery Records for Completed Orders")
            completed_order_ids = completed_orders['id'].tolist()
            completed_deliveries = delivery_records[delivery_records['order_id'].isin(completed_order_ids)]
            
            if not completed_deliveries.empty:
                # Merge with orders for display
                delivery_display = completed_deliveries.merge(
                    completed_orders, left_on='order_id', right_on='id', how='left', suffixes=('', '_order')
                )
                display_cols = ['id', 'order_id', 'client_name', 'cultivar', 'num_delivered', 'delivery_date', 'delivery_method', 'notes']
                available_cols = [col for col in display_cols if col in delivery_display.columns]
                st.dataframe(delivery_display[available_cols], use_container_width=True, hide_index=True)
                
                total_delivered = completed_deliveries['num_delivered'].sum()
                st.metric("Total Plants Delivered (Completed Orders)", total_delivered)
            else:
                st.info("No delivery records found for completed orders")
        
        # Export option
        csv = filtered_orders.to_csv(index=False)
        st.download_button(
            "Download Archive CSV",
            csv,
            "archive.csv",
            "text/csv"
        )
    else:
        st.info("No completed orders in archive")

# Footer
st.sidebar.divider()
st.sidebar.caption("Tissue Culture Tracker v1.0")
st.sidebar.caption(f"Database: {DB_PATH}")
