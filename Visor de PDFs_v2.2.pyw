

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF Viewer Pro v2.2 - Multi-Pestaña con Caché JXL
====================================================
Visor de PDFs multi-pestaña con soporte para caché JPEG-XL optimizado.

Requisitos:
    pip install PyMuPDF Pillow pyqt5
    pip install pillow-jxl  # Opcional pero recomendado
    
Autor: Cristian M. Veliz Cano
Versión: 2.2
Alojado en Megs:
https://mega.nz/file/Gp0CSJQB#ACzNicoFuz4ItsbSOIOzlE1lkFWELN6QbddhprMiqDQ
"""
##=========================================================================================
import sys
import os
import tempfile
import shutil
from io import BytesIO
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton, QStyle, QDialog,
    QFileDialog, QMessageBox, QVBoxLayout, QHBoxLayout, QProgressBar, QStackedWidget, QLineEdit, QFrame,
    QSizePolicy, QTabWidget, QShortcut, QListWidget, QListWidgetItem, QSplitter, QTextEdit)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QKeySequence, QPixmap, QImage, QFont, QIcon

# PDF Processing
import fitz  # PyMuPDF
from PIL import Image

import pillow_jxl
from pillow_jxl import Decoder

JXL_AVAILABLE = True

##===============================================================================
## CONFIGURACIÓN Y UTILIDADES
##===============================================================================

class PathUtil:
    """Utilidades para manejo de rutas."""
    
    @staticmethod
    def resource_path(relative_path):
        """Obtiene ruta absoluta, funciona en dev y PyInstaller."""
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)

# ============================================================
## WIDGET INDIVIDUAL DE PÁGINA PDF
# ============================================================

class PDFPageWidget(QWidget):
    """Widget individual que muestra una página de PDF con zoom y pan."""
    
    def __init__(self, pixmap, page_num, parent=None):
        super().__init__(parent)
        self.page_num = page_num
        self.original_pixmap = pixmap
        self.current_zoom = 1.0
        self.min_zoom = 0.1
        self.max_zoom = 5.0
        self.rotation = 0  # Agregar esta línea (0, 90, 180, 270)
        
        # Variables para pan con mouse
        self.panning = False
        self.last_mouse_pos = None
        
        self.init_ui()
        
    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #2c3e50;
                border: none;
            }
        """)
        
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Habilitar tracking de mouse para pan
        self.image_label.setMouseTracking(True)
        
        if self.original_pixmap and not self.original_pixmap.isNull():
            self.image_label.setPixmap(self.original_pixmap)
        
        self.scroll_area.setWidget(self.image_label)
        self.layout.addWidget(self.scroll_area)
        
        # Instalar event filter para capturar eventos del label
        self.image_label.installEventFilter(self)

    def rotate(self, degrees=90):
        """Rota la página 90° en sentido horario (o -90° antihorario)."""
        self.rotation = (self.rotation + degrees) % 360
        self.apply_rotation()
        
    def apply_rotation(self):
        """Aplica la rotación actual al pixmap mostrado."""
        if not self.original_pixmap or self.original_pixmap.isNull():
            return
            
        # Rotar el pixmap original
        transform = QtGui.QTransform().rotate(self.rotation)
        rotated = self.original_pixmap.transformed(transform, Qt.SmoothTransformation)
        
        # Aplicar zoom sobre el rotado
        new_width = int(rotated.width() * self.current_zoom)
        new_height = int(rotated.height() * self.current_zoom)
        
        scaled = rotated.scaled(
            new_width, 
            new_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.image_label.setPixmap(scaled)
        self.image_label.resize(scaled.size())
        
    def set_zoom(self, zoom_factor):
        """Modificado para respetar rotación."""
        self.current_zoom = max(self.min_zoom, min(self.max_zoom, zoom_factor))
        self.apply_rotation()  # En lugar de reescalar directamente
        
    def reset_zoom(self):
        self.rotation = 0  # Resetear rotación también
        self.set_zoom(1.0)

    def eventFilter(self, obj, event):
        """Captura eventos del image_label para zoom y pan."""
        if obj == self.image_label:
            if event.type() == QtCore.QEvent.Wheel:
                self.handle_wheel(event)
                return True
            elif event.type() == QtCore.QEvent.MouseButtonPress:
                self.handle_mouse_press(event)
                return True
            elif event.type() == QtCore.QEvent.MouseMove:
                self.handle_mouse_move(event)
                return True
            elif event.type() == QtCore.QEvent.MouseButtonRelease:
                self.handle_mouse_release(event)
                return True
        return super().eventFilter(obj, event)

    def handle_mouse_press(self, event):
        """Inicia el pan (arrastre) cuando hay zoom."""
        if event.button() == Qt.LeftButton and self.current_zoom > 1.0:
            self.panning = True
            self.last_mouse_pos = event.globalPos()
            self.image_label.setCursor(Qt.ClosedHandCursor)
    
    def handle_mouse_move(self, event):
        """Realiza el pan (arrastre) de la imagen."""
        if self.panning and self.last_mouse_pos:
            delta = event.globalPos() - self.last_mouse_pos
            self.last_mouse_pos = event.globalPos()
            
            # Mover las barras de scroll
            h_bar = self.scroll_area.horizontalScrollBar()
            v_bar = self.scroll_area.verticalScrollBar()
            
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
    
    def handle_mouse_release(self, event):
        """Termina el pan."""
        if event.button() == Qt.LeftButton:
            self.panning = False
            self.image_label.setCursor(Qt.ArrowCursor)

    def handle_wheel(self, event):
        """Zoom con Ctrl + Rueda del ratón."""
        if event.modifiers() == Qt.ControlModifier:
            # Calcular factor de zoom
            delta = event.angleDelta().y()
            if delta > 0:
                zoom_factor = self.current_zoom * 1.1
            else:
                zoom_factor = self.current_zoom / 1.1
            
            # Aplicar zoom
            self.set_zoom(zoom_factor)
            
            # CORRECCIÓN: Buscar el PDFViewer en la jerarquía de parents
            parent = self.parent()
            while parent and not isinstance(parent, PDFViewer):
                parent = parent.parent()
            
            if parent:
                parent.update_zoom_label(self.current_zoom)
        else:
            # Scroll normal si no hay Ctrl
            QtWidgets.QApplication.sendEvent(self.scroll_area, event)

    def update_zoom_label(self, zoom_value):
        """Actualiza el label de zoom desde PDFPageWidget."""
        self.global_zoom = zoom_value
        self.lbl_zoom.setText(f"{int(self.global_zoom * 100)}%")
        
    def set_zoom(self, zoom_factor):
        """Aplica zoom a la página."""
        self.current_zoom = max(self.min_zoom, min(self.max_zoom, zoom_factor))
        
        if self.original_pixmap and not self.original_pixmap.isNull():
            new_width = int(self.original_pixmap.width() * self.current_zoom)
            new_height = int(self.original_pixmap.height() * self.current_zoom)
            
            scaled = self.original_pixmap.scaled(
                new_width, 
                new_height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled)
            self.image_label.resize(scaled.size())
            
            # Cambiar cursor a open hand cuando hay zoom disponible
            if self.current_zoom > 1.0:
                self.image_label.setCursor(Qt.OpenHandCursor)
            else:
                self.image_label.setCursor(Qt.ArrowCursor)
            
    def get_zoom(self):
        return self.current_zoom
        
    def reset_zoom(self):
        self.set_zoom(1.0)


# ============================================================
## EXTRACTOR DE PDF CON SOPORTE JXL
# ============================================================

class PDFExtractorThread(QThread):
    """
    Hilo de extracción de páginas PDF.
    Soporta caché en PNG tradicional o JXL (JPEG-XL) optimizado.
    """
    page_extracted = pyqtSignal(int, int, QPixmap, str)  # current, total, pixmap, img_path
    extraction_complete = pyqtSignal(list)  # lista de rutas
    error_occurred = pyqtSignal(str)
    progress = pyqtSignal(int)  # porcentaje
    
    def __init__(self, pdf_path, dpi=150, temp_dir=None, 
                 usar_jxl=False, jxl_lossless=True, jxl_quality=95):
        super().__init__()
        self.pdf_path = pdf_path
        self.dpi = max(72, min(300, dpi))  # Limitar entre 72-300 DPI
        self.temp_dir = temp_dir or tempfile.mkdtemp(prefix="pdf_extract_")
        self.usar_jxl = usar_jxl and JXL_AVAILABLE
        self.jxl_lossless = jxl_lossless
        self.jxl_quality = max(1, min(100, jxl_quality))
        self.image_paths = []
        self._is_running = True
        self._cancelled = False
        
    def run(self):
        try:
            doc = fitz.open(self.pdf_path)
            total_pages = len(doc)
            
            for page_num in range(total_pages):
                if not self._is_running or self._cancelled:
                    break
                
                # Renderizar página
                page = doc[page_num]
                # Calcular matriz de escala según DPI
                scale = self.dpi / 72.0
                mat = fitz.Matrix(scale, scale)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                
                # Determinar formato y ruta de salida
                if self.usar_jxl:
                    ext = ".jxl"
                else:
                    ext = ".png"
                
                img_path = os.path.join(self.temp_dir, f"page_{page_num:04d}{ext}")
                
                # Guardar según formato seleccionado
                if self.usar_jxl:
                    self._save_as_jxl(pix, img_path)
                else:
                    pix.pil_save(img_path, "PNG", optimize=True)
                
                self.image_paths.append(img_path)
                
                # Crear pixmap para visualización inmediata (siempre PNG en memoria)
                img_data = pix.tobytes("png")
                image = QImage.fromData(img_data, "PNG")
                pixmap = QPixmap.fromImage(image)
                
                # Emitir señal
                self.page_extracted.emit(page_num + 1, total_pages, pixmap, img_path)
                self.progress.emit(int((page_num + 1) / total_pages * 100))
                
            doc.close()
            
            if not self._cancelled:
                self.extraction_complete.emit(self.image_paths)
            
        except Exception as e:
            self.error_occurred.emit(str(e))
    
    def _save_as_jxl(self, pix, img_path):
        """Convierte pixmap de fitz a JXL usando PIL."""
        # Crear imagen PIL desde datos de fitz
        imagen = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        
        # Guardar como JXL
        if self.jxl_lossless:
            imagen.save(img_path, format="JXL", lossless=True)
        else:
            imagen.save(img_path, format="JXL", lossless=False, 
                       quality=self.jxl_quality)
    
    def cancel(self):
        """Solicita cancelación del proceso."""
        self._cancelled = True
        self._is_running = False
        
    def cleanup(self):
        """Limpia archivos temporales."""
        self._is_running = False
        self.wait(1000)
        
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except:
                pass
    
    def __del__(self):
        self.cleanup()


# ============================================================
## VISOR DE PDF INDIVIDUAL (Contenido de cada pestaña)
# ============================================================

class PDFViewer(QWidget):
    """Visor individual de un PDF. Cada instancia va en una pestaña."""
    
    def __init__(self, pdf_path=None, usar_jxl=None, parent=None):
        super().__init__(parent)
        
        # Configuración de vista
        self.view_mode = "single"
        self.pdf_path = pdf_path
        self.global_zoom = 1.0
        self.zoom_step = 0.1
        self.current_page = 0        
        self.numpage = 0
        self.total_pages = 0
        self.page_cache = {}
        self.extractor_thread = None
        
        # ============================================================
        # CONFIGURACIÓN JXL - RECIBE DESDE LA VENTANA PRINCIPAL
        # ============================================================
        # Si no se especifica, usar el valor global por defecto
        if usar_jxl is None:
            self.usar_jxl = JXL_AVAILABLE
        else:
            self.usar_jxl = usar_jxl and JXL_AVAILABLE
            
        self.jxl_lossless = True       
        self.jxl_quality = 95          
        self.temp_dir = None           
        self.image_paths = []          
        
        self.init_ui()
        self.init_fullscreen()  # Al final del __init__
        
        if pdf_path:
            self.load_pdf(pdf_path)
    
    def init_ui(self):
        # Layout principal horizontal (sidebar + contenido)
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Sidebar de thumbnails (NUEVO)
        self.sidebar = ThumbnailSidebar()
        self.sidebar.page_clicked.connect(self.go_to_page)
        self.sidebar.setVisible(False)  # Oculto hasta que haya PDF
        main_layout.addWidget(self.sidebar)
        
        # Contenedor derecho (todo el contenido anterior)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        
        # ... (todo el código anterior de init_ui va aquí, 
        #      reemplazando 'layout' por 'right_layout')

        #layout = QVBoxLayout(self)
        #layout.setContentsMargins(0, 0, 0, 0)
        #layout.setSpacing(0)
        
        # Área de contenido con navegación
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout = content_layout

        # Botón toggle sidebar (nuevo)
        self.btn_toggle_sidebar = QPushButton("👁")
        self.btn_toggle_sidebar.setFixedSize(45, 35)
        self.btn_toggle_sidebar.setToolTip("Mostrar/Ocultar panel de páginas")
        self.btn_toggle_sidebar.setStyleSheet('''
            QPushButton {
                border: 1px; border-style:outset; 
                border-width:1px; 
                border-radius:10px;
                border-color:beige;
                font-size:18px;
                background-color: #e67e22;
                color: white;
            }
            QPushButton:hover {
                background-color: #d35400;
            }
            QPushButton:checked {
                background-color: #7f8c8d;
            }
        ''')
        self.btn_toggle_sidebar.setCheckable(True)
        self.btn_toggle_sidebar.setChecked(True)  # Inicialmente visible
        self.btn_toggle_sidebar.clicked.connect(self.toggle_sidebar)

		# Botones de rotación (agregar junto a los controles de zoom)
        btn_rotate_left = QPushButton("↺")
        btn_rotate_left.setFixedSize(35, 35)
        btn_rotate_left.setToolTip("Rotar 90° antihorario (←)")
        btn_rotate_left.setStyleSheet('''
            QPushButton {
                border: 1px outset;
                border-width: 1px;
                border-radius: 10px;
                border-color: beige;
                font-size: 18px;
                font-weight: bold;
                background-color: #9b59b6;
                color: white;
            }
            QPushButton:hover {
                background-color: #8e44ad;
            }
        ''')
        btn_rotate_left.clicked.connect(lambda: self.rotate_current_page(-90))
        
        btn_rotate_right = QPushButton("↻")
        btn_rotate_right.setFixedSize(35, 35)
        btn_rotate_right.setToolTip("Rotar 90° horario (→)")
        btn_rotate_right.setStyleSheet('''
            QPushButton {
                border: 1px outset;
                border-width: 1px;
                border-radius: 10px;
                border-color: beige;
                font-size: 18px;
                font-weight: bold;
                background-color: #9b59b6;
                color: white;
            }
            QPushButton:hover {
                background-color: #8e44ad;
            }
        ''')
        btn_rotate_right.clicked.connect(lambda: self.rotate_current_page(90))
        
        # Atajos de teclado para rotación
        QShortcut(QKeySequence(Qt.Key_Left), self, activated=lambda: self.rotate_current_page(-90))
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=lambda: self.rotate_current_page(90))
        
        # Botón anterior
        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedSize(30, 80)
        self.btn_prev.setStyleSheet('''
                background-color: rgba(52, 152, 219, 0.3);
                border-radius: 0;
                background-color: rgba(52, 152, 219, 0.6);
                font-size:16px;
                font-weight:bold;
                ''')
        self.btn_prev.clicked.connect(self.prev_page)
        self.btn_prev.setEnabled(False)
        content_layout.addWidget(self.btn_prev)
        
        # StackedWidget para páginas (modo single)
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setStyleSheet("background-color: #34495e;")
        self.stacked_widget.currentChanged.connect(self.on_page_changed)
        content_layout.addWidget(self.stacked_widget, stretch=1)
        
        # Botón siguiente
        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedSize(30, 80)
        self.btn_next.setStyleSheet("""
                background-color: rgba(52, 152, 219, 0.3);
                border-radius: 0;
                background-color: rgba(52, 152, 219, 0.6);
                font-size:16px;
                font-weight:bold;
                """)
        self.btn_next.clicked.connect(self.next_page)
        self.btn_next.setEnabled(False)
        content_layout.addWidget(self.btn_next)
        
        right_layout.addLayout(content_layout, stretch=1)
        
        # Barra inferior de controles
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(10, 10, 10, 10)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        
        self.lbl_navigation = QLabel("Página:")
        self.lbl_navigation.setStyleSheet("color: #ecf0f1; font-size: 20px; font-weight:bold;")
     
        self.page_display = QLineEdit(" - / -")
        self.page_display.setToolTip("Borra e Ingrea el Número de Pagenia\nLuego preciona Enter")
        self.page_display.setPlaceholderText(f"{self.numpage}")
        self.page_display.setFixedWidth(150)
        self.page_display.setFixedHeight(35)
        self.page_display.setStyleSheet("""
                color: #ecf0f1; 
                color:white; 
                font-size: 20px; 
                font-weight:bold;
                border: none;
                """
                )
        self.page_display.setAlignment(Qt.AlignRight)
        self.page_display.returnPressed.connect(self.set_page)

        # ============================================================
        # INDICADOR DE FORMATO - AHORA REFLEJA EL VALOR PASADO
        # ============================================================
        self.lbl_jxl_indicator = QLabel()
        self.update_format_indicator()  # Método que actualiza el estilo según el formato

        # Botón modo vista
        self.btn_view_mode = QPushButton("📖")
        self.btn_view_mode.setFixedSize(45, 35)
        self.btn_view_mode.setToolTip("Modo: Una página / Dos páginas")
        self.btn_view_mode.setStyleSheet('''
            QPushButton {
                border: 1px; border-style:outset; 
                border-width:1px; 
                border-radius:10px;
                border-color:beige;
                font-size:20px;
                background-color: #9b59b6;
                color: white;
            }
            QPushButton:hover {
                background-color: #8e44ad;
            }
        ''')
        self.btn_view_mode.clicked.connect(self.toggle_view_mode)
        
        # Botón Limpiar
        self.btn_erase = QPushButton("⛔")
        self.btn_erase.setStyleSheet('''
                QPushButton {
                border: 1px; border-style:outset; 
                border-width:1px; 
                border-radius:10px;
                border-color:beige;
                padding:0px;
                color: #ecf0f1;
                font-size:18px;
                text-align: center;
                }
                QPushButton:disabled {
                background-color: #3e3e3e;
                color: #bdc3c7;
                }
                ''')
        self.btn_erase.setToolTip("Limpia la Ventana del PDF")
        self.btn_erase.setFixedSize(45, 45)
        self.btn_erase.clicked.connect(self.clear_view)
        self.btn_erase.setEnabled(False)
        
        # Botón Home
        self.btn_home = QPushButton("🏠")
        self.btn_home.setStyleSheet('''
                QPushButton {
                border: 1px; border-style:outset; 
                border-width:1px; 
                border-radius:10px;
                border-color:beige;
                padding:0px;
                color: #ecf0f1;
                font-size:18px;
                text-align: center;
                }
                QPushButton:disabled {
                background-color: #3e3e3e;
                color: #bdc3c7;
                }
                ''')
        self.btn_home.setToolTip("Regreso Automatico Pagina #1")
        self.btn_home.setFixedSize(45, 45)
        self.btn_home.clicked.connect(self.home_page)
        self.btn_home.setEnabled(False)
        
        # Controles de zoom
        btn_zoom_out = QPushButton()
        btn_zoom_out.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipBackward))
        btn_zoom_out.setStyleSheet('''
                QPushButton {
                border: 1px; border-style:outset; 
                border-width:1px; 
                border-radius:10px;
                border-color:beige;
                font-size:20px;
                font-weight:bold;
                background-color: #3498db;
                color: white;
                }
                ''')
        btn_zoom_out.setFixedSize(30, 30)
        btn_zoom_out.setToolTip("Alejar")
        btn_zoom_out.clicked.connect(lambda: self.adjust_zoom(-self.zoom_step))
        
        self.lbl_zoom = QLabel("100%")
        self.lbl_zoom.setStyleSheet("color: #ecf0f1; min-width: 60px; font-size: 20px; font-weight:bold;")
        self.lbl_zoom.setAlignment(Qt.AlignCenter)
        
        btn_zoom_in = QPushButton()
        btn_zoom_in.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipForward))
        btn_zoom_in.setStyleSheet('''
                QPushButton {
                border: 1px; border-style:outset; 
                border-width:1px; 
                border-radius:10px;
                border-color:beige;
                font-size:20px;
                font-weight:bold;
                background-color: #3498db;
                color: white;
                }
                ''')
        btn_zoom_in.setFixedSize(30, 30)
        btn_zoom_in.setToolTip("Acercar")
        btn_zoom_in.clicked.connect(lambda: self.adjust_zoom(self.zoom_step))
        
        btn_fit = QPushButton("🔃")
        btn_fit.setStyleSheet('''
                QPushButton {
                border: 1px; border-style:outset; 
                border-width:1px; 
                border-radius:10px;
                border-color:beige;
                font-size:20px;
                font-weight:bold;
                background-color: #3498db;
                color: white;
                }
                ''')        
        btn_fit.setFixedSize(45, 35)
        btn_fit.setToolTip("Ajustar a ventana")
        btn_fit.clicked.connect(self.fit_to_window)
        
        # Armar barra inferior
        bottom_bar.addWidget(self.progress_bar)
        bottom_bar.addWidget(self.lbl_jxl_indicator)  # Indicador aquí
        bottom_bar.addWidget(self.btn_toggle_sidebar)  # NUEVO BOTÓN AQUÍ
        bottom_bar.addWidget(btn_rotate_left)   # ← Agregar
        bottom_bar.addWidget(btn_rotate_right)  # ← Agregar
        bottom_bar.addSpacing(10)
        bottom_bar.addStretch()
        bottom_bar.addWidget(self.btn_view_mode)
        bottom_bar.addWidget(self.btn_home)
        
        bottom_bar.addWidget(self.btn_erase)
        bottom_bar.addWidget(self.lbl_navigation)
        bottom_bar.addWidget(self.page_display)
        bottom_bar.addSpacing(20)
        bottom_bar.addWidget(btn_zoom_out)
        bottom_bar.addWidget(self.lbl_zoom)
        bottom_bar.addWidget(btn_zoom_in)
        bottom_bar.addWidget(btn_fit)
        
        bottom_widget = QWidget()
        bottom_widget.setLayout(bottom_bar)
        bottom_widget.setStyleSheet("background-color: #2c3e50;")
        right_layout.addWidget(bottom_widget)
        
        # Al final, agregar right_widget al main_layout
        main_layout.addWidget(right_widget, stretch=1)
        
        # Atajos de teclado
        QShortcut(QKeySequence(Qt.Key_Left), self, activated=self.prev_page)
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=self.next_page)
        QShortcut(QKeySequence(Qt.Key_Up), self, activated=lambda: self.adjust_zoom(self.zoom_step))
        QShortcut(QKeySequence(Qt.Key_Down), self, activated=lambda: self.adjust_zoom(-self.zoom_step))

    def rotate_current_page(self, degrees):
        """Rota la página actual."""
        if self.current_page in self.page_cache:
            page_widget = self.page_cache[self.current_page]
            page_widget.rotate(degrees)
            
            # Actualizar la miniatura en el sidebar
            if hasattr(self, 'sidebar'):
                # Crear pixmap rotado para thumbnail
                pixmap = page_widget.image_label.pixmap()
                if pixmap:
                    self.sidebar.set_thumbnail_pixmap(self.current_page, pixmap)

    def init_fullscreen(self):
        """Inicializa modo presentación."""
        self.is_fullscreen = False
        self.pre_fullscreen_geometry = None
        
        # Atajo F11
        self.shortcut_fullscreen = QShortcut(QKeySequence("F11"), self)
        self.shortcut_fullscreen.activated.connect(self.toggle_fullscreen)
        
        # Doble clic en el área de contenido para fullscreen
        self.stacked_widget.mouseDoubleClickEvent = self.on_double_click_fullscreen
        
        # Botón de salir en modo fullscreen (esquina superior)
        self.btn_exit_fs = QPushButton("✕ Salir", self)
        self.btn_exit_fs.setFixedSize(80, 30)
        self.btn_exit_fs.setStyleSheet("""
            QPushButton {
                background-color: rgba(231, 76, 60, 0.9);
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(192, 57, 43, 1.0);
            }
        """)
        self.btn_exit_fs.clicked.connect(self.exit_fullscreen)
        self.btn_exit_fs.hide()
        
        # Label de instrucción temporal
        self.lbl_fs_hint = QLabel("F11 o doble clic para salir", self)
        self.lbl_fs_hint.setStyleSheet("""
            color: rgba(255,255,255,0.7);
            font-size: 12px;
            background-color: rgba(0,0,0,0.5);
            padding: 5px 10px;
            border-radius: 4px;
        """)
        self.lbl_fs_hint.hide()

    def on_double_click_fullscreen(self, event):
        """Doble clic activa/desactiva fullscreen."""
        self.toggle_fullscreen()

    def toggle_fullscreen(self):
        """Activa/desactiva modo pantalla completa."""
        window = self.window()
        
        if not self.is_fullscreen:
            # Entrar a fullscreen
            self.pre_fullscreen_geometry = window.geometry()
            window.showFullScreen()
            self.is_fullscreen = True
            
            # Ocultar barra de herramientas y sidebar
            if hasattr(self, 'sidebar'):
                self.sidebar_was_visible = self.sidebar.isVisible()
                self.sidebar.hide()
            else:
                self.sidebar_was_visible = False
                
            # Mostrar botón de salir
            self.btn_exit_fs.show()
            self.btn_exit_fs.raise_()
            self.position_exit_button()
            
            # Mostrar hint temporal
            self.lbl_fs_hint.show()
            self.lbl_fs_hint.raise_()
            self.position_hint()
            QtCore.QTimer.singleShot(3000, self.lbl_fs_hint.hide)
            
        else:
            self.exit_fullscreen()

    def exit_fullscreen(self):
        """Sale del modo pantalla completa."""
        window = self.window()
        window.showNormal()
        
        if self.pre_fullscreen_geometry:
            window.setGeometry(self.pre_fullscreen_geometry)
        
        self.is_fullscreen = False
        
        # Restaurar sidebar si estaba visible
        if hasattr(self, 'sidebar') and self.sidebar_was_visible:
            self.sidebar.show()
        
        self.btn_exit_fs.hide()
        self.lbl_fs_hint.hide()

    def position_exit_button(self):
        """Posiciona el botón de salir en esquina superior derecha."""
        if hasattr(self, 'btn_exit_fs'):
            margin = 10
            x = self.width() - self.btn_exit_fs.width() - margin
            self.btn_exit_fs.move(x, margin)

    def position_hint(self):
        """Posiciona el hint en la parte inferior."""
        if hasattr(self, 'lbl_fs_hint'):
            self.lbl_fs_hint.move(
                (self.width() - self.lbl_fs_hint.width()) // 2,
                self.height() - 50
            )

    def resizeEvent(self, event):
        """Sobreescribe para reposicionar controles en fullscreen."""
        super().resizeEvent(event)
        if self.is_fullscreen:
            self.position_exit_button()
            self.position_hint()

    def toggle_sidebar(self):
        """Muestra u oculta el panel lateral de miniaturas."""
        if hasattr(self, 'sidebar'):
            is_visible = self.sidebar.isVisible()
            self.sidebar.setVisible(not is_visible)
            
            # Actualizar estado del botón
            self.btn_toggle_sidebar.setChecked(not is_visible)

            if is_visible:
            	self.btn_toggle_sidebar.setText("🙈")
            	self.btn_toggle_sidebar.setToolTip("Mostrar panel de páginas")
            else:
            	self.btn_toggle_sidebar.setText("👁")
            	self.btn_toggle_sidebar.setToolTip("Ocultar panel de páginas")

    def go_to_page(self, page_num):
        """Navega a una página específica (desde thumbnail o código)."""
        if 0 <= page_num < self.total_pages:
            self.current_page = page_num
            self.stacked_widget.setCurrentIndex(page_num)
            self.update_navigation_buttons()
            self.lbl_navigation.setText(f"Página:")
            self.page_display.setText(f" {page_num + 1} / {self.total_pages}")
            
            # Actualizar sidebar si existe
            if hasattr(self, 'sidebar'):
                self.sidebar.update_selection(page_num)

    def update_zoom_label(self, zoom_value):
        """Actualiza el label de zoom desde PDFPageWidget."""
        self.global_zoom = zoom_value
        self.lbl_zoom.setText(f"{int(self.global_zoom * 100)}%")
    # ============================================================
    # MÉTODOS JXL - DECODIFICACIÓN
    # ============================================================
    
    def _decodificar_jxl(self, ruta_jxl):
        """
        Decodifica archivo JXL a QPixmap.
        Pipeline: JXL → Decoder → PIL → PNG memoria → QImage → QPixmap
        """
        try:
            # Leer archivo JXL
            with open(ruta_jxl, "rb") as f:
                datos_jxl = f.read()
            
            # Decodificar con pillow_jxl
            decoder = Decoder(parallel=True)
            info, pixels = decoder(datos_jxl)
            
            # Validar modo de color
            modo = info.mode if info.mode in ("RGB", "RGBA", "L", "LA") else "RGB"
            
            # Reconstruir imagen PIL desde bytes crudos
            imagen = Image.frombytes(modo, (info.width, info.height), pixels)
            
            # Convertir a RGB/RGBA para Qt
            if imagen.mode not in ("RGB", "RGBA"):
                imagen = imagen.convert("RGB")
            
            # PIL → PNG en memoria → QPixmap
            buffer = BytesIO()
            imagen.save(buffer, format="PNG")
            buffer.seek(0)
            
            # Cargar en Qt
            qimage = QImage()
            qimage.loadFromData(buffer.getvalue(), "PNG")
            pixmap = QPixmap.fromImage(qimage)
            
            return pixmap
            
        except Exception as e:
            print(f"❌ Error decodificando JXL: {e}")
            # Fallback: intentar cargar directamente o retornar vacío
            if os.path.exists(ruta_jxl):
                return QPixmap(ruta_jxl)
            return QPixmap()
    
    # ============================================================
    # CARGA Y GESTIÓN DE PDF
    # ============================================================
    
    def load_pdf(self, file_path):
        """Carga un PDF en este visor con soporte JXL opcional."""
        self.pdf_path = file_path
        self.btn_erase.setEnabled(True)
        self.btn_home.setEnabled(True)
        
        # Limpiar caché anterior si existe
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        
        # Crear nuevo directorio temporal
        self.temp_dir = tempfile.mkdtemp(prefix="pdf_cache_")
        self.image_paths = []
        
        self.clear_view()
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # Crear extractor con soporte JXL
        self.extractor_thread = PDFExtractorThread(
            file_path, 
            dpi=150,
            temp_dir=self.temp_dir,
            usar_jxl=self.usar_jxl,
            jxl_lossless=self.jxl_lossless,
            jxl_quality=self.jxl_quality
        )
        self.extractor_thread.page_extracted.connect(self.on_page_extracted)
        self.extractor_thread.extraction_complete.connect(self.on_extraction_complete)
        self.extractor_thread.error_occurred.connect(self.on_extraction_error)
        self.extractor_thread.start()

    def on_page_extracted(self, current, total, pixmap, img_path=None):
        """Recibe página extraída del hilo."""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        
        if img_path and img_path.endswith('.jxl'):
            self.image_paths.append(img_path)
        elif img_path:
            self.image_paths.append(img_path)
        
        # Crear widget de página con zoom/pan
        page_widget = PDFPageWidget(pixmap, current - 1, parent=self)
        self.stacked_widget.addWidget(page_widget)
        self.page_cache[current - 1] = page_widget
        
        # Actualizar sidebar con thumbnail (NUEVO)
        if current == 1:  # Primera página, inicializar sidebar
            self.sidebar.set_page_count(total)
            self.sidebar.setVisible(True)
        
        # Establecer miniatura (escalada)
        self.sidebar.set_thumbnail_pixmap(current - 1, pixmap)
        
        self.lbl_navigation.setText(f"Página:")
        self.page_display.setText(f" {current} / {total}")
    
    def on_extraction_complete(self, image_paths):
        """Extracción finalizada."""
        self.total_pages = len(image_paths)
        self.progress_bar.setVisible(False)
        
        if self.total_pages > 0:
            self.lbl_navigation.setText(f"Página:")
            self.page_display.setText(f" 1 / {self.total_pages}")
            self.update_navigation_buttons()
            self.stacked_widget.setCurrentIndex(0)
            self.fit_to_window()
            
            # Seleccionar primera página en sidebar
            self.sidebar.update_selection(0)
    
    def on_extraction_error(self, error_msg):
        """Error en extracción."""
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "Error", f"No se pudo abrir el PDF:\n{error_msg}")
    
    def clear_view(self):
        """Limpia la vista actual."""
        while self.stacked_widget.count():
            widget = self.stacked_widget.widget(0)
            self.stacked_widget.removeWidget(widget)
            widget.deleteLater()
        self.page_cache.clear()
        self.current_page = 0
        self.total_pages = 0
        
        # Limpiar widget de doble página si existe
        if hasattr(self, 'double_page_widget'):
            self.double_page_widget.setVisible(False)
        self.stacked_widget.setVisible(True)
    
    # ============================================================
    # MODO DOBLE PÁGINA
    # ============================================================
    
    def toggle_view_mode(self):
        """Alterna entre vista simple y doble."""
        if self.view_mode == "single":
            self.view_mode = "double"
            self.btn_view_mode.setText("📄")
            self.show_double_page()
        else:
            self.view_mode = "single"
            self.btn_view_mode.setText("📖")
            self.show_single_page()

    def show_double_page(self):
        """Muestra dos páginas lado a lado."""
        if not hasattr(self, 'double_page_widget'):
            self.double_page_widget = QWidget()
            right_layout = QHBoxLayout(self.double_page_widget)
            right_layout.setContentsMargins(0, 0, 0, 0)
            right_layout.setSpacing(5)
            
            self.left_page = QLabel()
            self.left_page.setAlignment(Qt.AlignCenter)
            self.left_page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.left_page.setStyleSheet("background-color: #34495e;")
            
            self.right_page = QLabel()
            self.right_page.setAlignment(Qt.AlignCenter)
            self.right_page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.right_page.setStyleSheet("background-color: #34495e;")
            
            right_layout.addWidget(self.left_page)
            right_layout.addWidget(self.right_page)
            
            self.content_layout.addWidget(self.double_page_widget)
        
        self.stacked_widget.setVisible(False)
        self.double_page_widget.setVisible(True)
        self.update_double_page_view()

    def update_double_page_view(self):
        """Actualiza las imágenes en vista doble."""
        if self.view_mode != "double":
            return
        
        # Página izquierda: actual (par) o anterior (impar)
        left_page_num = self.current_page if self.current_page % 2 == 0 else self.current_page - 1
        if left_page_num < 0:
            left_page_num = 0
            
        # Página derecha: siguiente
        right_page_num = left_page_num + 1
        
        # Cargar página izquierda
        if left_page_num in self.page_cache:
            left_pixmap = self.page_cache[left_page_num].original_pixmap
            scaled_left = self.scale_for_double(left_pixmap)
            self.left_page.setPixmap(scaled_left)
        else:
            self.left_page.clear()
            self.left_page.setText("— Inicio —")
            self.left_page.setStyleSheet("color: #7f8c8d; font-size: 14px; background-color: #34495e;")
        
        # Cargar página derecha
        if right_page_num < self.total_pages and right_page_num in self.page_cache:
            right_pixmap = self.page_cache[right_page_num].original_pixmap
            scaled_right = self.scale_for_double(right_pixmap)
            self.right_page.setPixmap(scaled_right)
        else:
            self.right_page.clear()
            self.right_page.setText("— Fin —")
            self.right_page.setStyleSheet("color: #7f8c8d; font-size: 14px; background-color: #34495e;")

    def scale_for_double(self, pixmap):
        """Escala el pixmap para caber en mitad de pantalla."""
        if not pixmap or pixmap.isNull():
            return QPixmap()
        
        available_w = self.stacked_widget.width() // 2 - 20
        available_h = self.stacked_widget.height() - 40
        
        return pixmap.scaled(available_w, available_h, 
                            Qt.KeepAspectRatio, 
                            Qt.SmoothTransformation)

    def show_single_page(self):
        """Muestra una página a la vez."""
        self.stacked_widget.setVisible(True)
        if hasattr(self, 'double_page_widget'):
            self.double_page_widget.setVisible(False)
        self.update_navigation_buttons()
    
    # ============================================================
    # NAVEGACIÓN
    # ============================================================
    def home_page(self):

        self.current_page = int(0)
        self.stacked_widget.setCurrentIndex(self.current_page)
        self.update_navigation_buttons()

    def prev_page(self):
        """Retrocede página considerando el modo de vista."""
        if self.view_mode == "single":
            if self.current_page > 0:
                self.current_page -= 1
                self.stacked_widget.setCurrentIndex(self.current_page)
                self.sidebar.update_selection(self.current_page)  # NUEVO
        else:
            if self.current_page >= 2:
                self.current_page -= 2
            else:
                self.current_page = 0
            self.update_double_page_view()
            self.sidebar.update_selection(self.current_page)  # NUEVO
        
        self.update_navigation_buttons()
        self.lbl_navigation.setText(f"Página:")
        self.page_display.setText(f" {self.current_page + 1} / {self.total_pages}")

    def next_page(self):
        """Avanza página considerando el modo de vista."""
        if self.view_mode == "single":
            if self.current_page < self.total_pages - 1:
                self.current_page += 1
                self.stacked_widget.setCurrentIndex(self.current_page)
                self.sidebar.update_selection(self.current_page)  # NUEVO
        else:
            if self.current_page < self.total_pages - 2:
                self.current_page += 2
                self.update_double_page_view()
            elif self.current_page < self.total_pages - 1:
                self.current_page += 1
                self.update_double_page_view()
            self.sidebar.update_selection(self.current_page)  # NUEVO
        
        self.update_navigation_buttons()
        self.lbl_navigation.setText(f"Página:")
        self.page_display.setText(f" {self.current_page + 1} / {self.total_pages}")

    def set_page(self):
        try:
            self.current_page = int(self.page_display.text())-1
            self.stacked_widget.setCurrentIndex(self.current_page)
            self.sidebar.update_selection(self.current_page)  # NUEVO
            self.btn_home.setEnabled(True)
            self.update_navigation_buttons()
        except Exception as e:
            print(e)
            QMessageBox.critical(self, "Error", f"Para Buscar, debes Borrar e ingresar el Número de Pagina.")
            self.page_display.clear()
    
    def on_page_changed(self, index):
        """Sincroniza índice cuando cambia en stacked."""
        self.current_page = index
        self.lbl_navigation.setText(f"Página:")
        self.page_display.setText(f" {index + 1} / {self.total_pages}")
        self.update_navigation_buttons()
        
        # Sincronizar sidebar
        if hasattr(self, 'sidebar'):
            self.sidebar.update_selection(index)
        
        if self.view_mode == "double":
            self.update_double_page_view()

    def update_navigation_buttons(self):
        """Actualiza estado de botones de navegación."""
        self.btn_prev.setEnabled(self.current_page > 0)
        self.btn_next.setEnabled(self.current_page < self.total_pages - 1)
    
    # ============================================================
    # ZOOM
    # ============================================================
    
    def adjust_zoom(self, delta):
        """Ajusta el zoom global."""
        self.global_zoom += delta
        self.global_zoom = max(0.1, min(3.0, self.global_zoom))
        self.apply_zoom_to_current()
        self.lbl_zoom.setText(f"{int(self.global_zoom * 100)}%")
    
    def fit_to_window(self):
        """Ajusta zoom para que la página quepa en la ventana."""
        if self.current_page not in self.page_cache:
            return
        
        widget = self.page_cache[self.current_page]
        if not widget.original_pixmap or widget.original_pixmap.isNull():
            return
        
        available = self.stacked_widget.size()
        pixmap_size = widget.original_pixmap.size()
        
        zoom_w = available.width() / pixmap_size.width()
        zoom_h = available.height() / pixmap_size.height()
        
        self.global_zoom = min(zoom_w, zoom_h) * 0.95
        self.apply_zoom_to_current()
        self.lbl_zoom.setText(f"{int(self.global_zoom * 100)}%")
    
    def apply_zoom_to_current(self):
        """Aplica zoom a la página actual."""
        if self.current_page in self.page_cache:
            self.page_cache[self.current_page].set_zoom(self.global_zoom)
    
    # ============================================================
    # UTILIDADES
    # ============================================================
    
    def get_tab_title(self):
        """Retorna el nombre del archivo para la pestaña."""
        if self.pdf_path:
            name = os.path.basename(self.pdf_path)
            if len(name) > 20:
                return name[:17] + "..."
            return name
        return "Sin título"
    
    def cleanup(self):
        """Limpia recursos al cerrar."""
        if self.extractor_thread:
            self.extractor_thread.cleanup()
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def update_format_indicator(self):
        """Actualiza el indicador de formato según self.usar_jxl."""
        if self.usar_jxl:
            self.lbl_jxl_indicator.setText("JXL")
            self.lbl_jxl_indicator.setStyleSheet("""
                color: #2ecc71;
                font-size: 12px;
                font-weight: bold;
                padding: 4px 10px;
                border-radius: 4px;
                background-color: rgba(46, 204, 113, 0.3);
                border: 1px solid rgba(46, 204, 113, 0.5);
            """)
            self.lbl_jxl_indicator.setToolTip("Formato de caché: JPEG-XL (Optimizado)")
        else:
            self.lbl_jxl_indicator.setText("PNG")
            self.lbl_jxl_indicator.setStyleSheet("""
                color: #e74c3c;
                font-size: 12px;
                font-weight: bold;
                padding: 4px 10px;
                border-radius: 4px;
                background-color: rgba(231, 76, 60, 0.3);
                border: 1px solid rgba(231, 76, 60, 0.5);
            """)
            self.lbl_jxl_indicator.setToolTip("Formato de caché: PNG (Estándar)")

# ============================================================
## VENTANA PRINCIPAL: CONTENEDOR DE PESTAÑAS
# ============================================================
class PDFTabViewer(QWidget):
    """Ventana principal con QTabWidget que contiene múltiples PDFViewers."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("📚 PDF Viewer Pro v2.2 - Multi-Pestaña (JXL Optimizado)")        
        
        # Icono
        self.Ico_app = PathUtil.resource_path('Ico\\1.png')
        self.setWindowIcon(QtGui.QIcon(self.Ico_app))

        self.usar_jxl_global = JXL_AVAILABLE  # Valor por defecto
        
        self.init_ui()
        self.apply_styles()
        self.center_on_screen()
    
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Barra superior
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(10, 10, 10, 10)
        
        btn_open = QPushButton("📂 Abrir PDF")
        btn_open.setStyleSheet('''
                font-size:14px;
                font-weight:bold;''')
        btn_open.setToolTip("Ctrl+O")
        btn_open.clicked.connect(self.open_new_pdf)
        btn_open.setMinimumWidth(120)
        
        btn_new_tab = QPushButton("+ Nueva pestaña")
        btn_new_tab.setToolTip("Ctrl+T")
        btn_new_tab.clicked.connect(self.add_empty_tab)

        # === SELECTOR PNG/JXL (NUEVO - EN LA BARRA SUPERIOR) ===
        self.format_selector = self.create_format_selector()
        
        self.lbl_status = QLabel("Listo" + (" | Modo JXL ✅" if JXL_AVAILABLE else " | Modo PNG"))
        self.lbl_status.setStyleSheet("color: #bdc3c7;")
        
        toolbar.addWidget(btn_open)
        toolbar.addWidget(btn_new_tab)
        toolbar.addSpacing(15)
        toolbar.addWidget(self.format_selector)  # ← AQUÍ ESTÁ EL SELECTOR
        toolbar.addStretch()
        toolbar.addWidget(self.lbl_status)
        
        toolbar_widget = QWidget()
        toolbar_widget.setLayout(toolbar)
        toolbar_widget.setStyleSheet("background-color: #2c3e50;")
        main_layout.addWidget(toolbar_widget)
        
        # QTabWidget principal
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        
        # Estilo para pestañas
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #1a1a2e;
            }
            QTabBar::tab {
                background-color: #2c3e50;
                color: #bdc3c7;
                padding: 8px 20px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #34495e;
                color: #ecf0f1;
            }
            QTabBar::tab:hover {
                background-color: #3498db;
                color: white;
            }
        """)
        
        main_layout.addWidget(self.tab_widget, stretch=1)
        
        # Atajos globales
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.open_new_pdf)
        QShortcut(QKeySequence("Ctrl+T"), self, activated=self.add_empty_tab)
        QShortcut(QKeySequence("Ctrl+W"), self, activated=self.close_current_tab)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)
        QShortcut(QKeySequence('Ctrl+K'), self, activated=self.show_shortcuts)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.close)
        
        # Aceptar drag & drop
        self.setAcceptDrops(True)
        
        # Agregar primera pestaña vacía
        self.add_empty_tab()
        
        # Atajos de teclado
        QShortcut(QKeySequence('F1'), self).activated.connect(self.show_app_info)

        self.show_app_info()
    
    ##=========================================================================================

    def show_app_info(self):
        dialog = app_info(self)
        dialog.exec_()
    
    def show_shortcuts(self):
        dialog_k = key_info(self)
        dialog_k.exec_()

    ##=========================================================================================

    def apply_styles(self):
        self.setStyleSheet("""
            QWidget {
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 11px;
            }
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QProgressBar {
                border: 1px solid #34495e;
                border-radius: 3px;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #3498db;
            }
        """)
    
    def center_on_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        w, h = 1200, 725
        x = (screen.width() - w) // 2
        y = (screen.height() - h) // 2+8
        self.setGeometry(x, y, w, h)
    
    def add_empty_tab(self):
        """Agrega una pestaña vacía."""
        empty_widget = QWidget()
        right_layout = QVBoxLayout(empty_widget)
        
        msg = QLabel("📄 Arrastra un PDF aquí\no usa el botón 'Abrir PDF'")
        msg.setAlignment(Qt.AlignCenter)
        msg.setStyleSheet("""
            QLabel {
                color: #7f8c8d;
                font-size: 18px;
            }
        """)
        right_layout.addWidget(msg)
        
        index = self.tab_widget.addTab(empty_widget, "Nueva pestaña")
        self.tab_widget.setCurrentIndex(index)

    def open_new_pdf(self):
        """Abre uno o varios PDFs en nuevas pestañas."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Abrir PDF(s)", "", "Archivos PDF (*.pdf)"
        )
        
        if file_paths:
            self.create_pdf_tabs(file_paths)

    def create_pdf_tabs(self, file_paths):
        """Crea pestañas para uno o varios PDFs."""
        if isinstance(file_paths, str):
            file_paths = [file_paths]
        
        opened_count = 0
        skipped_count = 0
        
        for file_path in file_paths:
            # Verificar si ya está abierto
            already_open = False
            for i in range(self.tab_widget.count()):
                widget = self.tab_widget.widget(i)
                if isinstance(widget, PDFViewer) and widget.pdf_path == file_path:
                    self.tab_widget.setCurrentIndex(i)
                    already_open = True
                    skipped_count += 1
                    break
            
            if already_open:
                continue
            
            # Crear nuevo visor PASANDO EL FORMATO SELECCIONADO
            viewer = PDFViewer(file_path, usar_jxl=self.usar_jxl_global)
            title = viewer.get_tab_title()
            
            index = self.tab_widget.addTab(viewer, f"📄 {title}")
            self.tab_widget.setTabToolTip(index, file_path)
            opened_count += 1
        
        if opened_count > 0:
            self.tab_widget.setCurrentIndex(self.tab_widget.count() - 1)
            formato = "JXL" if self.usar_jxl_global else "PNG"
            self.lbl_status.setText(f"Abiertos: {opened_count} PDF(s) en modo {formato}")
        elif skipped_count > 0:
            self.lbl_status.setText(f"{skipped_count} archivo(s) ya estaban abiertos")
    
    def close_tab(self, index):
        """Cierra una pestaña específica y limpia caché JXL."""
        widget = self.tab_widget.widget(index)
        
        # Limpiar recursos si es un PDFViewer
        if isinstance(widget, PDFViewer):
            widget.cleanup()  # Limpia thread y directorio temporal
        
        self.tab_widget.removeTab(index)
        
        if self.tab_widget.count() == 0:
            self.add_empty_tab()
    
    def close_current_tab(self):
        """Cierra la pestaña actual."""
        current = self.tab_widget.currentIndex()
        if current >= 0:
            self.close_tab(current)
    
    def on_tab_changed(self, index):
        """Cuando cambia de pestaña."""
        if index >= 0:
            widget = self.tab_widget.widget(index)
            if isinstance(widget, PDFViewer):
                self.lbl_status.setText(f"📄 {widget.get_tab_title()}")
            else:
                self.lbl_status.setText("Nueva pestaña")
    
    # Drag & Drop
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        """Acepta múltiples PDFs arrastrados."""
        pdf_files = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                if path.lower().endswith('.pdf'):
                    pdf_files.append(path)
        
        if pdf_files:
            self.create_pdf_tabs(pdf_files)
    
    def closeEvent(self, event):
        """Limpieza al cerrar la aplicación."""
        # Limpiar todas las pestañas
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if isinstance(widget, PDFViewer):
                widget.cleanup()
        event.accept()

    def create_format_selector(self):
        """Crea el grupo de radio buttons para seleccionar formato PNG/JXL."""
        # Widget contenedor
        format_widget = QWidget()
        format_layout = QHBoxLayout(format_widget)
        format_layout.setContentsMargins(8, 2, 8, 2)
        format_layout.setSpacing(10)
        
        # Label descriptivo
        lbl_format = QLabel("Formato de caché:")
        lbl_format.setStyleSheet("color: #bdc3c7; font-size: 12px; font-weight: bold;")
        format_layout.addWidget(lbl_format)
        
        # Grupo de radio buttons
        self.radio_group = QtWidgets.QButtonGroup(self)
        
        # Radio button PNG
        self.radio_png = QtWidgets.QRadioButton("PNG")
        self.radio_png.setStyleSheet("""
            QRadioButton {
                color: #ecf0f1;
                font-size: 12px;
                spacing: 6px;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
            }
            QRadioButton::indicator:checked {
                background-color: #e74c3c;
                border: 2px solid #c0392b;
                border-radius: 8px;
            }
            QRadioButton::indicator:unchecked {
                background-color: #34495e;
                border: 2px solid #7f8c8d;
                border-radius: 8px;
            }
        """)
        self.radio_png.setToolTip("Usar PNG estándar (compatible con todos los sistemas)")
        
        # Radio button JXL
        self.radio_jxl = QtWidgets.QRadioButton("JXL")
        self.radio_jxl.setStyleSheet("""
            QRadioButton {
                color: #ecf0f1;
                font-size: 12px;
                spacing: 6px;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
            }
            QRadioButton::indicator:checked {
                background-color: #2ecc71;
                border: 2px solid #27ae60;
                border-radius: 8px;
            }
            QRadioButton::indicator:unchecked {
                background-color: #34495e;
                border: 2px solid #7f8c8d;
                border-radius: 8px;
            }
        """)
        self.radio_jxl.setToolTip("Usar JPEG-XL (mejor compresión, menor tamaño, más rápido)")
        
        # Deshabilitar JXL si no está disponible
        if not JXL_AVAILABLE:
            self.radio_jxl.setEnabled(False)
            self.radio_jxl.setToolTip("JPEG-XL no disponible - instala: pip install pillow-jxl")
        
        # Agregar al grupo
        self.radio_group.addButton(self.radio_png)
        self.radio_group.addButton(self.radio_jxl)
        
        # Setear selección inicial
        if self.usar_jxl_global and JXL_AVAILABLE:
            self.radio_jxl.setChecked(True)
        else:
            self.radio_png.setChecked(True)
        
        # Conectar señal de cambio
        self.radio_group.buttonToggled.connect(self.on_format_changed)
        
        format_layout.addWidget(self.radio_png)
        format_layout.addWidget(self.radio_jxl)
        
        # Borde decorativo con fondo
        format_widget.setStyleSheet("""
            QWidget {
                background-color: rgba(52, 73, 94, 0.8);
                border-radius: 6px;
                border: 1px solid rgba(127, 140, 141, 0.5);
            }
            QLabel {
                background-color: transparent;
                border: none;
            }
        """)
        
        return format_widget
    
    def on_format_changed(self, button, checked):
        """Actualiza la variable global cuando cambia la selección."""
        if not checked:
            return
            
        if button == self.radio_jxl and JXL_AVAILABLE:
            self.usar_jxl_global = True
        else:
            self.usar_jxl_global = False
        
        # Actualizar label de estado
        self.update_status_label()
    
    def update_status_label(self):
        """Actualiza el label de estado según el formato seleccionado."""
        if self.usar_jxl_global and JXL_AVAILABLE:
            self.lbl_status.setText("Listo | Modo JXL ✅ (Optimizado)")
            self.lbl_status.setStyleSheet("color: #2ecc71; font-weight: bold;")
        else:
            self.lbl_status.setText("Listo | Modo PNG (Estándar)")
            self.lbl_status.setStyleSheet("color: #bdc3c7;")

##======================================================================================
## ➜ Conversor, a Miniaturas, Panel, Izquierdo, Togglee, Genial.
##======================================================================================
class ThumbnailSidebar(QWidget):
    """Panel lateral con miniaturas de páginas."""
    
    page_clicked = pyqtSignal(int)  # Emite número de página al hacer clic
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.thumbnails = []  # Lista de tuplas (widget, page_num)
        self.current_page = 0
        
        self.init_ui()
        
    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(5)
        
        # Título
        title = QLabel("Páginas")
        title.setStyleSheet("""
            color: #ecf0f1;
            font-size: 14px;
            font-weight: bold;
            padding: 5px;
            border-bottom: 1px solid #34495e;
        """)
        title.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(title)
        
        # Scroll area para thumbnails
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #2c3e50;
                border: none;
            }
        """)
        
        # Widget contenedor de thumbnails
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setSpacing(5)
        self.container_layout.setAlignment(Qt.AlignTop)
        
        self.scroll_area.setWidget(self.container)
        self.layout.addWidget(self.scroll_area)
        
        # Estilo del sidebar
        self.setFixedWidth(150)
        self.setStyleSheet("""
            ThumbnailSidebar {
                background-color: #2c3e50;
                border-right: 1px solid #34495e;
            }
        """)
    
    def set_page_count(self, count):
        """Crea los widgets de thumbnail vacíos."""
        # Limpiar existentes
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.thumbnails = []
        
        for i in range(count):
            thumb_widget = self.create_thumbnail_widget(i)
            self.container_layout.addWidget(thumb_widget)
            self.thumbnails.append(thumb_widget)
        
        self.update_selection(0)
    
    def create_thumbnail_widget(self, page_num):
        """Crea un widget de miniatura individual."""
        widget = QWidget()
        widget.setFixedSize(130, 170)
        widget.setCursor(Qt.PointingHandCursor)
        widget.setStyleSheet("""
            QWidget {
                background-color: #34495e;
                border: 2px solid transparent;
                border-radius: 4px;
            }
            QWidget:hover {
                background-color: #3d566e;
                border: 2px solid #3498db;
            }
            QWidget.selected {
                background-color: #2980b9;
                border: 2px solid #3498db;
            }
        """)
        
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(3)
        
        # Label para la imagen (placeholder inicialmente)
        img_label = QLabel()
        img_label.setAlignment(Qt.AlignCenter)
        img_label.setFixedSize(116, 136)
        img_label.setStyleSheet("background-color: #2c3e50; border: none;")
        img_label.setText("...")
        img_label.setAlignment(Qt.AlignCenter)
        
        # Número de página
        num_label = QLabel(f"Pág. {page_num + 1}")
        num_label.setAlignment(Qt.AlignCenter)
        num_label.setStyleSheet("color: #bdc3c7; font-size: 10px; border: none;")
        
        layout.addWidget(img_label)
        layout.addWidget(num_label)
        
        # Guardar referencias
        widget.img_label = img_label
        widget.page_num = page_num
        widget.num_label = num_label
        
        # Evento de clic
        widget.mousePressEvent = lambda e, p=page_num: self.on_thumbnail_click(p)
        
        return widget
    
    def set_thumbnail_pixmap(self, page_num, pixmap):
        """Establece la imagen de una miniatura."""
        if 0 <= page_num < len(self.thumbnails):
            thumb = self.thumbnails[page_num]
            # Escalar a tamaño de thumbnail
            scaled = pixmap.scaled(110, 130, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            thumb.img_label.setPixmap(scaled)
            thumb.img_label.setText("")
    
    def update_selection(self, page_num):
        """Resalta la miniatura de la página actual."""
        for i, thumb in enumerate(self.thumbnails):
            if i == page_num:
                thumb.setStyleSheet("""
                    QWidget {
                        background-color: #2980b9;
                        border: 2px solid #3498db;
                        border-radius: 4px;
                    }
                    QWidget:hover {
                        background-color: #3498db;
                    }
                """)
                # CORRECCIÓN: Llamar ensureWidgetVisible en el scroll_area, no en el thumb
                self.scroll_area.ensureWidgetVisible(thumb)
            else:
                thumb.setStyleSheet("""
                    QWidget {
                        background-color: #34495e;
                        border: 2px solid transparent;
                        border-radius: 4px;
                    }
                    QWidget:hover {
                        background-color: #3d566e;
                        border: 2px solid #3498db;
                    }
                """)
        
        self.current_page = page_num
    
    def on_thumbnail_click(self, page_num):
        """Maneja clic en miniatura."""
        self.update_selection(page_num)
        self.page_clicked.emit(page_num)

##======================================================================================
## ➜ Diálogo de Información - PDF Viewer Pro v2.2
##======================================================================================
class app_info(QDialog):
    """Diálogo de información sobre PDF Viewer Pro"""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Guardar referencia al padre
        self.parent = parent

        # Configuración de ventana
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setWindowTitle("⚡ Información del Sistema")
        self.setFixedSize(640, 520)
        self.setModal(True)

        self.init_ui()

    def init_ui(self):
        """Inicializa la interfaz del diálogo"""

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # =====================================================================
        # ESTILO BASE
        # =====================================================================

        self.setStyleSheet("""
            QDialog {
                background-color: #0a0a0f;
                color: #e6edf3;
            }

            QLabel {
                color: #e6edf3;
                font-family: 'Segoe UI', 'Consolas', sans-serif;
            }

            QTextEdit {
                background-color: #111118;
                color: #00ff80;
                border: 1px solid #00c3ff;
                border-radius: 6px;
                padding: 10px;
                font-family: 'Consolas', monospace;
                font-size: 11pt;
                selection-background-color: #00c3ff;
            }

            QPushButton {
                background-color: #1a1a2e;
                color: #00c3ff;
                border: 1px solid #00c3ff;
                border-radius: 6px;
                padding: 8px 20px;
                font-weight: bold;
                font-size: 11px;
                min-height: 32px;
            }

            QPushButton:hover {
                background-color: #00c3ff;
                color: #0a0a0f;
            }
        """)

        # =====================================================================
        # HEADER
        # =====================================================================

        header_layout = QHBoxLayout()

        title_box = QVBoxLayout()

        main_title = QLabel("⚡ PDF VIEWER PRO")
        main_title.setStyleSheet("""
            font-size: 18pt;
            font-weight: bold;
            color: #00ff88;
            font-family: 'Consolas', monospace;
        """)
        main_title.setAlignment(Qt.AlignCenter)

        subtitle = QLabel("📚 Visor Profesional de Documentos PDF")
        subtitle.setStyleSheet("""
            font-size: 10pt;
            color: #00c3ff;
            font-family: 'Consolas', monospace;
        """)
        subtitle.setAlignment(Qt.AlignCenter)

        version = QLabel("Versión 2.2 | Multi-Pestaña + Caché JPEG-XL")
        version.setStyleSheet("""
            font-size: 9pt;
            color: #888888;
            font-family: 'Consolas', monospace;
        """)
        version.setAlignment(Qt.AlignCenter)

        title_box.addWidget(main_title)
        title_box.addWidget(subtitle)
        title_box.addWidget(version)

        header_layout.addStretch()
        header_layout.addLayout(title_box)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # =====================================================================
        # SEPARADOR
        # =====================================================================

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #00c3ff;")
        line.setFixedHeight(2)

        layout.addWidget(line)

        # =====================================================================
        # INFORMACIÓN
        # =====================================================================

        info_text = QTextEdit()
        info_text.setReadOnly(True)

        info_content = """
╔══════════════════════════════════════════════════════════════════╗
║                    DESARROLLADO POR                              ║
║              👉 Cristian M. Veliz Cano ✔                         ║
╚══════════════════════════════════════════════════════════════════╝

📊 ESPECIFICACIONES TÉCNICAS

📄 Motor PDF:          PyMuPDF (fitz)
🖥 Framework GUI:      PyQt5
🖼 Procesamiento:      Pillow
🗜 Caché optimizado:   JPEG-XL (JXL)
📦 Caché estándar:     PNG
🐍 Lenguaje:           Python 3.x

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚡ FUNCIONALIDADES PRINCIPALES

📚 Visor PDF

   • Visualización de documentos PDF
   • Renderizado de páginas mediante PyMuPDF
   • Carga progresiva de páginas
   • Procesamiento mediante hilo independiente
   • Barra de progreso durante la extracción
   • Navegación página por página

🗂 MULTI-PES­­TAÑA

   • Múltiples documentos PDF abiertos simultáneamente
   • Cada PDF posee su propio visor independiente
   • Creación de nuevas pestañas
   • Cierre individual de pestañas
   • Detección de archivos ya abiertos
   • Apertura múltiple de documentos

🖼 CACHÉ DE PÁGINAS

   • Caché temporal de páginas renderizadas
   • Formato PNG estándar
   • Formato JPEG-XL (JXL) optimizado
   • Selección PNG/JXL desde la interfaz
   • JPEG-XL con compresión Lossless
   • JPEG-XL con calidad configurable
   • Decodificación JXL mediante Pillow

🔍 ZOOM Y NAVEGACIÓN

   • Zoom configurable
   • Rango de zoom hasta 300%
   • Ajuste automático a la ventana
   • Zoom mediante botones
   • Zoom mediante Ctrl + rueda del ratón
   • Desplazamiento (Pan) mediante ratón
   • Indicador visual del porcentaje de zoom

🔄 ROTACIÓN

   • Rotación 90° en sentido horario
   • Rotación 90° en sentido antihorario
   • Rotación mediante botones
   • Rotación mediante teclado
   • Soporte para rotación 0°, 90°, 180° y 270°


📖 MODOS DE VISUALIZACIÓN

   • Modo página individual
   • Modo doble página
   • Visualización de páginas lado a lado
   • Cambio instantáneo entre modos


🖼 PANEL DE MINIATURAS

   • Vista lateral de páginas
   • Miniaturas generadas automáticamente
   • Navegación mediante selección de miniatura
   • Resaltado de página actual
   • Desplazamiento automático hacia la página seleccionada
   • Panel mostrar / ocultar


⛶ MODO PANTALLA COMPLETA

   • Pantalla completa mediante F11
   • Activación mediante doble clic
   • Botón de salida de pantalla completa
   • Restauración automática de la geometría original
   • Ocultación temporal del panel lateral
   • Indicador de ayuda temporal


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⌨️ ATAJOS DE TECLADO

   Ctrl+O      →  Abrir PDF(s)

   Ctrl+T      →  Nueva pestaña

   Ctrl+W      →  Cerrar pestaña actual

   Ctrl+Q      →  Cerrar aplicación

   ESC         →  Cerrar aplicación

   F11         →  Pantalla completa

   ←           →  Página anterior / Rotar izquierda*

   →           →  Página siguiente / Rotar derecha*

   ↑           →  Aumentar zoom

   ↓           →  Reducir zoom


   * Los atajos de rotación están definidos directamente
     sobre el visor de página.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📂 APERTURA DE ARCHIVOS

   • Abrir mediante selector de archivos
   • Abrir múltiples PDFs simultáneamente
   • Drag & Drop de archivos PDF
   • Apertura mediante argumentos de línea de comandos
   • Detección automática de archivos PDF

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎨 INTERFAZ

   Tema:             Dark / Modern
   Framework:        PyQt5
   Motor PDF:        PyMuPDF
   Procesamiento:    Pillow
   Caché:            PNG / JPEG-XL
   Interfaz:         Multi-Pestaña
   Panel:            Miniaturas laterales
   Visualización:    Página simple / doble

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚙️ PROCESAMIENTO

   • Extracción de páginas mediante QThread
   • Renderizado configurable de 72 a 300 DPI
   • Procesamiento progresivo
   • Caché temporal por documento
   • Limpieza automática de archivos temporales
   • Cancelación del proceso de extracción
   • Manejo de errores durante la carga

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔐 PRIVACIDAD

   ✔ Procesamiento local de documentos
   ✔ No requiere conexión a Internet
   ✔ No utiliza servicios externos
   ✔ Archivos PDF procesados localmente
   ✔ Caché almacenada temporalmente
   ✔ Limpieza de caché al cerrar el documento

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📄 LICENCIA

MIT License

Copyright (c) 2026 Cristian M. Veliz Cano

Se concede permiso, de forma gratuita, a cualquier persona que
obtenga una copia de este software, para utilizarlo sin restricción,
incluyendo los derechos de uso, copia, modificación y distribución.

EL SOFTWARE SE PROPORCIONA "TAL CUAL", SIN GARANTÍA DE NINGÚN TIPO.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 "Visualización PDF sin complicaciones." 📚

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """

        info_text.setText(info_content)

        layout.addWidget(info_text)

        # =====================================================================
        # BOTÓN CERRAR
        # =====================================================================

        close_layout = QHBoxLayout()
        close_layout.addStretch()

        close_button = QPushButton("✔ ACEPTAR")
        close_button.setFixedWidth(120)
        close_button.clicked.connect(self.close)

        close_layout.addWidget(close_button)

        close_layout.addStretch()

        layout.addLayout(close_layout)

##====================================================================================
## ➜ Diálogo de Atajos de Teclado y Controles - PDF Viewer Pro v2.2
##====================================================================================
class key_info(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint
        )

        self.setWindowTitle("⌨️ Atajos de Teclas y Controles")
        self.setFixedSize(620, 650)
        self.setModal(True)

        self.init_ui()

    def init_ui(self):

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # =====================================================================
        # ESTILO
        # =====================================================================

        self.setStyleSheet("""
            QDialog {
                background-color: #0a0a0f;
                color: #e6edf3;
            }

            QLabel {
                color: #e6edf3;
                font-family: 'Segoe UI', 'Consolas', sans-serif;
            }

            QTextEdit {
                background-color: #111118;
                color: #F1F1F1;
                border: 1px solid #00c3ff;
                border-radius: 5px;
                padding: 8px;
                font-family: 'Consolas', monospace;
                font-size: 10.5pt;
                selection-background-color: #00c3ff;
            }

            QPushButton {
                background-color: #1a1a2e;
                color: white;
                border: 1px solid #00c3ff;
                border-radius: 5px;
                padding: 7px 20px;
                font-weight: bold;
            }

            QPushButton:hover {
                background-color: #00c3ff;
                color: black;
            }
        """)

        # =====================================================================
        # TÍTULO
        # =====================================================================

        title = QLabel("⌨️ ATAJOS DE TECLAS Y CONTROLES")
        title.setAlignment(Qt.AlignCenter)

        title.setStyleSheet("""
            QLabel {
                font-size: 16pt;
                font-weight: bold;
                color: #00c3ff;
                font-family: 'Consolas', monospace;
            }
        """)

        layout.addWidget(title)

        # =====================================================================
        # INFORMACIÓN
        # =====================================================================

        info_text = QTextEdit()
        info_text.setReadOnly(True)

        info_text.setText("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⌨️ ATAJOS DEL TECLADO
PDF VIEWER PRO v2.2


📎 CTRL + O
📂 Abrir PDF(s)

• Abre el selector de archivos.
• Permite seleccionar uno o varios documentos PDF.
• Cada PDF seleccionado se abre en una nueva pestaña.
• Si el PDF ya está abierto, no se duplica.


📎 CTRL + T
➕ Nueva pestaña

• Crea una nueva pestaña vacía.
• Permite posteriormente cargar un PDF.
• También sirve como espacio preparado para
  arrastrar un documento PDF.


📎 CTRL + W
❌ Cerrar pestaña actual

• Cierra únicamente la pestaña actualmente seleccionada.
• Libera los recursos asociados al PDF.
• Limpia el directorio temporal utilizado por el visor.


📎 CTRL + Q
⛔ Cerrar aplicación

• Cierra completamente PDF Viewer Pro.


📎 ESC
⛔ Cerrar aplicación

• Cierra inmediatamente PDF Viewer Pro.


📎 F11
⛶ Pantalla completa

• Activa / desactiva el modo de pantalla completa.
• Permite aprovechar todo el espacio disponible
  para visualizar el documento.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📄 NAVEGACIÓN ENTRE PÁGINAS


📎 ←  FLECHA IZQUIERDA
◀ Página anterior

• Retrocede a la página anterior del documento.


📎 →  FLECHA DERECHA
▶ Página siguiente

• Avanza a la página siguiente del documento.


📎 ↑  FLECHA ARRIBA
🔍 Aumentar Zoom

• Incrementa el nivel de zoom de visualización.


📎 ↓  FLECHA ABAJO
🔎 Reducir Zoom

• Reduce el nivel de zoom de visualización.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🖱️ CONTROLES DEL RATÓN


📎 RUEDA DEL RATÓN
↕ Desplazamiento vertical

• Permite desplazarse por el documento.
• Facilita recorrer páginas y contenido
  sin utilizar las barras de desplazamiento.


📎 CTRL + RUEDA DEL RATÓN
🔍 Zoom

• Mantener presionada la tecla CTRL.
• Mover la rueda hacia arriba → Aumenta el zoom.
• Mover la rueda hacia abajo → Reduce el zoom.


📎 BOTÓN IZQUIERDO + ARRASTRAR
✋ Desplazamiento / PAN

• Permite mover visualmente la página cuando
  se encuentra ampliada.
• Útil para recorrer zonas del documento
  que quedan fuera del área visible.


📎 DOBLE CLIC
⛶ Pantalla completa

• Doble clic sobre el área de visualización
  para entrar o salir del modo pantalla completa.


📎 CLIC EN MINIATURA
📄 Ir a una página

• Selecciona directamente una página desde
  el panel lateral de miniaturas.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🖼️ PANEL DE MINIATURAS


📎 CLIC EN UNA MINIATURA
📄 Seleccionar página

• Cambia directamente a la página seleccionada.


📎 PANEL DE MINIATURAS
👁 Mostrar páginas

• Permite visualizar una representación reducida
  de las páginas del documento.


📎 SCROLL DEL PANEL
↕ Recorrer miniaturas

• Permite desplazarse por la lista de páginas
  cuando el documento contiene muchas páginas.


📎 SELECCIÓN AUTOMÁTICA
🎯 Página actual

• La miniatura correspondiente a la página actual
  queda resaltada.
• El panel desplaza automáticamente la miniatura
  seleccionada hasta hacerla visible.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔍 CONTROLES DE ZOOM


📎 BOTÓN +
🔍 Aumentar

• Incrementa el tamaño de visualización.


📎 BOTÓN -
🔎 Reducir

• Disminuye el tamaño de visualización.


📎 AJUSTAR / FIT
📐 Ajustar página

• Ajusta la página al área disponible del visor.


📎 CTRL + RUEDA ↑
🔍 Zoom +

• Aumenta progresivamente la visualización.


📎 CTRL + RUEDA ↓
🔎 Zoom -

• Reduce progresivamente la visualización.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔄 ROTACIÓN DEL DOCUMENTO


📎 ROTAR IZQUIERDA
↶ 90°

• Gira la página 90 grados hacia la izquierda.


📎 ROTAR DERECHA
↷ 90°

• Gira la página 90 grados hacia la derecha.


📎 BOTONES DE ROTACIÓN
🔄 Rotación manual

• Permiten modificar la orientación de la página
  sin modificar el archivo PDF original.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📖 MODOS DE VISUALIZACIÓN


📎 PÁGINA INDIVIDUAL
📄 Vista simple

• Muestra una página a la vez.


📎 DOBLE PÁGINA
📖 Vista doble

• Muestra dos páginas simultáneamente.
• Ideal para documentos tipo libro o revista.


📎 FULLSCREEN
⛶ Vista completa

• Oculta elementos innecesarios de la interfaz
  para maximizar el área de lectura.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🗂️ PESTAÑAS


📎 + NUEVA PESTAÑA
➕

• Crea un visor vacío.


📎 CERRAR PESTAÑA
❌

• Cierra únicamente el documento seleccionado.


📎 CAMBIAR DE PESTAÑA
↔

• Permite alternar entre los diferentes PDFs
  abiertos simultáneamente.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📂 DRAG & DROP


📎 ARRASTRAR PDF → VENTANA
📄 Cargar documento

• Arrastra uno o varios archivos PDF desde
  el Explorador de Windows directamente
  sobre PDF Viewer Pro.


📎 MÚLTIPLES PDF
📚 Apertura múltiple

• Es posible arrastrar varios documentos PDF
  simultáneamente.
• Cada documento válido se abre en su propia pestaña.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚡ RESUMEN RÁPIDO


   CTRL + O       → Abrir PDF(s)

   CTRL + T       → Nueva pestaña

   CTRL + W       → Cerrar pestaña actual

   CTRL + Q       → Cerrar aplicación

   ESC            → Cerrar aplicación

   F11            → Pantalla completa

   ←              → Página anterior

   →              → Página siguiente

   ↑              → Aumentar zoom

   ↓              → Reducir zoom

   CTRL + RUEDA   → Zoom

   RUEDA          → Desplazamiento

   DOBLE CLIC     → Pantalla completa

   CLIC MINIATURA → Ir a página

   ARRASTRAR PDF  → Abrir PDF


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 CONSEJO DE USO

📚 Para lectura normal:

   • Utilice la rueda del ratón para desplazarse.
   • Utilice CTRL + rueda para controlar el zoom.
   • Utilice las miniaturas para saltar rápidamente
     a cualquier página.


🔍 Para documentos ampliados:

   • Aumente el zoom.
   • Mantenga el botón izquierdo del ratón y arrastre
     para recorrer las diferentes zonas de la página.


⛶ Para lectura sin distracciones:

   • Presione F11.
   • También puede utilizar doble clic.


📑 Para trabajar con varios documentos:

   • Utilice CTRL + T para crear pestañas.
   • Utilice CTRL + O para cargar PDFs.
   • Utilice CTRL + W para cerrar la pestaña actual.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📌 INFORMACIÓN

PDF VIEWER PRO v2.2
Multi-Pestaña • Caché PNG/JXL • Miniaturas • Zoom • Rotación

Desarrollado por:
Cristian M. Veliz Cano


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")

        layout.addWidget(info_text)

        # =====================================================================
        # BOTÓN CERRAR
        # =====================================================================

        close_button = QPushButton("✔ Cerrar")
        close_button.clicked.connect(self.close)
        close_button.setFixedHeight(32)

        layout.addWidget(close_button)

# ============================================================
## MAIN
# ============================================================

def main():
    # Configuración High DPI
    QtCore.QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QtCore.QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Viewer Pro")
    app.setApplicationVersion("2.2")
    
    # Verificar argumentos (abrir con...)
    initial_pdfs = []
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if os.path.exists(arg) and arg.lower().endswith('.pdf'):
                initial_pdfs.append(arg)
    
    viewer = PDFTabViewer()
    
    if initial_pdfs:
        viewer.create_pdf_tabs(initial_pdfs)
    
    viewer.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()