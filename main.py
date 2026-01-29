import os
import threading
import traceback
import shutil
from kivy.utils import platform
from kivy.clock import Clock
from kivymd.app import MDApp
from kivymd.uix.screen import Screen
from kivymd.uix.textfield import MDTextField
from kivymd.uix.button import MDFillRoundFlatButton, MDFlatButton
from kivymd.uix.label import MDLabel
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.dialog import MDDialog
import yt_dlp

class YtdlpLogger:
    """
    Classe auxiliar para interceptar logs do yt-dlp.
    Evita poluição no console e permite redirecionar erros se necessário.
    """
    def debug(self, msg):
        pass  # Ignora mensagens de debug para manter o log limpo

    def warning(self, msg):
        print(f"[WARN] {msg}")

    def error(self, msg):
        print(f"[ERROR] {msg}")

class YouTubeDownloaderApp(MDApp):
    """
    Classe principal da aplicação.
    Gerencia a UI (KivyMD) e a lógica de download/processamento de arquivos.
    """
    dialog = None 
    
    def build(self):
        """
        Constrói a interface gráfica e solicita permissões em tempo de execução
        se estiver rodando no Android.
        """
        self.theme_cls.primary_palette = "Red"
        screen = Screen()

        # --- Componentes de UI ---
        self.label_status = MDLabel(
            text="Cole o link do YouTube",
            halign="center", pos_hint={"center_x": 0.5, "center_y": 0.8},
            theme_text_color="Secondary",
            font_style="Subtitle1"
        )

        self.input_url = MDTextField(
            hint_text="URL do Vídeo",
            pos_hint={"center_x": 0.5, "center_y": 0.6}, size_hint_x=0.8
        )

        button_box = MDBoxLayout(
            orientation='horizontal',
            spacing=20,
            adaptive_size=True,
            pos_hint={"center_x": 0.5, "center_y": 0.45}
        )

        # Botões com lambdas para passar argumentos específicos
        btn_video = MDFillRoundFlatButton(
            text="VÍDEO (MP4)",
            on_release=lambda x: self.iniciar_download('video')
        )
        
        btn_audio = MDFillRoundFlatButton(
            text="ÁUDIO (M4A/MP3)",
            md_bg_color=(0, 0.5, 0, 1), # Cor verde personalizada
            on_release=lambda x: self.iniciar_download('audio')
        )

        button_box.add_widget(btn_video)
        button_box.add_widget(btn_audio)
        
        screen.add_widget(self.label_status)
        screen.add_widget(self.input_url)
        screen.add_widget(button_box)
        
        # Solicitação de permissões de armazenamento para Android (Runtime Permissions)
        if platform == 'android':
            from android.permissions import request_permissions, Permission
            request_permissions([
                Permission.INTERNET, 
                Permission.WRITE_EXTERNAL_STORAGE, 
                Permission.READ_EXTERNAL_STORAGE
            ])

        return screen

    def iniciar_download(self, tipo):
        """
        Valida a entrada e inicia o processo em uma Thread separada.
        IMPORTANTE: O download deve ser assíncrono para não travar a UI principal do App.
        """
        url = self.input_url.text
        if not url:
            self.label_status.text = "Erro: URL vazia"
            return
        
        self.label_status.text = f"Baixando {tipo}..."
        # Threading é essencial aqui para evitar o erro "Application Not Responding" (ANR)
        threading.Thread(target=self.baixar_midia, args=(url, tipo)).start()

    def baixar_midia(self, url, tipo):
        """
        Lógica core do download utilizando yt-dlp.
        Gerencia caminhos de arquivo (Android Sandbox vs Desktop).
        """
        try:
            # Define onde o arquivo será salvo temporariamente
            private_path = "."
            if platform == 'android':
                # No Android, usamos o diretório privado do app primeiro para garantir permissão de escrita
                from jnius import autoclass
                PythonActivity = autoclass('org.kivy.android.PythonActivity')
                private_path = PythonActivity.mActivity.getExternalFilesDir(None).getAbsolutePath()

            # Configurações do yt-dlp
            ydl_opts = {
                'outtmpl': f'{private_path}/%(title)s.%(ext)s',
                'noplaylist': True,
                'ignoreerrors': True,
                'logger': YtdlpLogger(),
            }

            # Configuração específica para conversão de áudio
            if tipo == 'audio':
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'prefer_ffmpeg': False, # Kivy/Buildozer requer configuração cuidadosa do ffmpeg
                    'keepvideo': False,
                })
            else:
                ydl_opts.update({'format': 'best'}) # Melhor qualidade de vídeo disponível
            
            # Execução do Download
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename_original = ydl.prepare_filename(info)
                
            final_path = filename_original
            
            # Tratamento para mudança de extensão pós-conversão (webm/m4a -> mp3)
            if tipo == 'audio':
                base = os.path.splitext(filename_original)[0]
                if os.path.exists(base + ".mp3"):
                    final_path = base + ".mp3"
                elif os.path.exists(base + ".m4a"):
                    final_path = base + ".m4a"

            # Se for Android, movemos do Sandbox privado para a pasta pública de Downloads
            if platform == 'android':
                final_path = self.mover_para_download_publico(final_path)

            # Usa Clock.schedule_once para atualizar a UI a partir da Thread principal (MainThread)
            Clock.schedule_once(lambda x: self.mostrar_sucesso(final_path), 0)

        except Exception as e:
            traceback.print_exc()
            Clock.schedule_once(lambda x: self.mostrar_erro(str(e)), 0)

    def mover_para_download_publico(self, original_path):
        """
        Move o arquivo da pasta privada do app para a pasta pública 'Downloads' do Android.
        Utiliza JNI (jnius) para acessar as variáveis de ambiente do sistema Android.
        """
        try:
            if not os.path.exists(original_path):
                return f"Erro: Arquivo não encontrado em {original_path}"

            from jnius import autoclass
            Environment = autoclass('android.os.Environment')
            # Obtém o caminho absoluto da pasta Downloads nativa do Android
            public_dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS).getAbsolutePath()
            
            file_name = os.path.basename(original_path)
            destination_path = os.path.join(public_dir, file_name)

            # Remove arquivo existente se houver conflito
            if os.path.exists(destination_path):
                os.remove(destination_path)

            # Move o arquivo fisicamente
            shutil.copy2(original_path, destination_path)
            os.remove(original_path)
            
            # Notifica a galeria do Android sobre o novo arquivo
            self.atualizar_galeria(destination_path)
            
            return destination_path
        except Exception as e:
            print(f"Erro ao mover: {e}")
            return original_path 

    def atualizar_galeria(self, filepath):
        """
        Força o Android MediaScanner a indexar o novo arquivo.
        Sem isso, o arquivo existe mas não aparece nos apps de Galeria ou Música.
        """
        try:
            from jnius import autoclass
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            MediaScannerConnection = autoclass('android.media.MediaScannerConnection')
            MediaScannerConnection.scanFile(PythonActivity.mActivity, [filepath], None, None)
        except Exception as e:
            print(f"Erro scanner: {e}")

    # --- Métodos de Feedback UI ---
    
    def mostrar_sucesso(self, path):
        self.label_status.text = "Concluído!"
        nome_arq = os.path.basename(path)
        self.dialog = MDDialog(
            title="Sucesso!",
            text=f"Salvo em Downloads:\n{nome_arq}",
            buttons=[MDFlatButton(text="OK", on_release=self.fechar_dialog)],
        )
        self.dialog.open()

    def mostrar_erro(self, erro_text):
        self.label_status.text = "Erro"
        self.dialog = MDDialog(
            title="Erro",
            text=str(erro_text)[:300], # Trunca erros muito longos para caber na tela
            buttons=[MDFlatButton(text="FECHAR", on_release=self.fechar_dialog)],
        )
        self.dialog.open()

    def fechar_dialog(self, inst):
        if self.dialog: self.dialog.dismiss()

if __name__ == "__main__":
    YouTubeDownloaderApp().run()
