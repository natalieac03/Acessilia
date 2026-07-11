import cv2
import numpy as np
from PIL import Image
import io
from core.utils.logger import logger

VIT_MAX_DIMENSION = 1344


def resize_image(image_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size

    if w > VIT_MAX_DIMENSION or h > VIT_MAX_DIMENSION:
        ratio = VIT_MAX_DIMENSION / max(w, h)
        new_w, new_h = int(w * ratio), int(h * ratio)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        logger.debug("Imagem redimensionada: {}x{} -> {}x{}", w, h, new_w, new_h)
        return buf.getvalue()

    return image_bytes


def enhance_image_for_ocr(image_bytes: bytes) -> bytes:
    """Pre-processamento pensado para documento ESCANEADO ou FOTOGRAFADO.

    NAO use em PDF nativo: paginas nativas ja sao nitidas, nao tem ruido para
    remover, e o denoise/CLAHE so introduzem artefatos. Veja `preparar_imagem_regiao`.
    """
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            return image_bytes

        img = cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

<<<<<<< HEAD
        coords = np.column_stack(np.where(gray > 0))
        angle = cv2.minAreaRect(coords)[-1]

        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle

        if abs(angle) > 0.5:
            (h, w) = img.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            img = cv2.warpAffine(
                img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
            )
            logger.debug("Imagem rotacionada em {:.2f} graus", angle)
=======
        # CORRECAO DE BUG: a versao antiga usava `np.where(gray > 0)`, que
        # seleciona TODOS os pixels nao-pretos. Como branco = 255 > 0, isso
        # pegava ~95% da imagem, e o minAreaRect media o angulo do retangulo
        # inteiro em vez do angulo do TEXTO. O deskew ficava inutil (ou pior:
        # dependendo da versao do OpenCV, podia girar a imagem em 90 graus).
        # Agora selecionamos apenas os pixels ESCUROS, que sao o texto.
        _, binaria = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )
        coords = np.column_stack(np.where(binaria > 0))

        # Sem pixels escuros suficientes nao ha texto para alinhar.
        proporcao_texto = len(coords) / max(1, gray.size)
        if len(coords) < 50 or proporcao_texto > 0.9:
            logger.debug("Deskew ignorado (sem texto claro para medir angulo)")
        else:
            angle = cv2.minAreaRect(coords)[-1]

            if angle < -45:
                angle = -(90 + angle)
            else:
                angle = -angle

            # Trava de seguranca: deskew corrige inclinacao de scanner (poucos
            # graus). Um angulo grande e sinal de calculo errado - nao girar.
            if 0.5 < abs(angle) <= 15.0:
                (h, w) = img.shape[:2]
                center = (w // 2, h // 2)
                M = cv2.getRotationMatrix2D(center, angle, 1.0)
                img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
                logger.debug("Imagem rotacionada em {:.2f} graus", angle)
            elif abs(angle) > 15.0:
                logger.debug(
                    "Deskew ignorado: angulo suspeito de {:.2f} graus", angle
                )
>>>>>>> 837afd5 (Atualiza projeto com alterações locais)

        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        L, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        cl = clahe.apply(L)
        limg = cv2.merge((cl, a, b))
        img = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

        _, buffer = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        return buffer.tobytes()

    except Exception as e:
        logger.error("Erro no pré-processamento de imagem: {}", e)
        return image_bytes


<<<<<<< HEAD
=======
# --------------------------------------------------------------------------- #
# Preparo de imagem por tipo de regiao.
#
# Regra: PDF nativo (diagramas, logos, codigo renderizado) ja chega nitido.
# Aplicar denoise + CLAHE nele so borra tracos finos e cria artefatos - foi
# medido: +78% de bytes e -7,3% de nitidez, sem ganho nenhum.
# So documento ESCANEADO se beneficia desse tratamento.
# --------------------------------------------------------------------------- #
TIPOS_QUE_PRECISAM_DE_REALCE = {"text_scanned", "unknown"}


def preparar_imagem_regiao(
    png_bytes: bytes,
    classification: str,
    qualidade: int = 95,
) -> bytes:
    """Converte o recorte PNG para o formato final enviado a IA de visao.

    - Escaneado/ambiguo -> realce (denoise + deskew + CLAHE).
    - PDF nativo        -> UMA unica passagem de JPEG, sem realce.

    Antes eram DUAS compressoes JPEG com perda (q85 e depois q95) em cima
    de um recorte ja pequeno. Agora e uma so, com qualidade alta.
    """
    if classification in TIPOS_QUE_PRECISAM_DE_REALCE:
        realçada = enhance_image_for_ocr(png_bytes)
        return resize_image(realçada)

    # PDF nativo: so redimensiona (se necessario) e codifica uma vez.
    try:
        img = Image.open(io.BytesIO(png_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")

        w, h = img.size
        if w > VIT_MAX_DIMENSION or h > VIT_MAX_DIMENSION:
            ratio = VIT_MAX_DIMENSION / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
            logger.debug(
                "Recorte redimensionado: {}x{} -> {}x{}", w, h, *img.size
            )

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=qualidade, optimize=True)
        return buf.getvalue()
    except Exception as e:
        logger.error("Erro ao preparar recorte: {}", e)
        return png_bytes

>>>>>>> 837afd5 (Atualiza projeto com alterações locais)
def is_math_likely(text: str) -> bool:
    math_indicators = [
        "=",
        "+",
        "-",
        "*",
        "/",
        "^",
        "√",
        "∫",
        "∑",
        "π",
        "θ",
        "²",
        "³",
        "log",
        "sin",
        "cos",
        "tan",
    ]
    count = sum(1 for indicator in math_indicators if indicator in text)
    return count > 2
