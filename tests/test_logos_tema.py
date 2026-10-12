"""O tema muda só o traço neutro, não a paleta das marcas."""
from pathlib import Path
import xml.etree.ElementTree as ET

from robinbandit.ui.logos import para_fundo_escuro


def test_cores_cohere_cerebras_e_huggingface_sao_preservadas():
    base = Path(__file__).resolve().parents[1] / "src/robinbandit/assets/providers"
    for nome in ("cohere", "cerebras", "huggingface", "deepinfra"):
        original = ET.fromstring((base / (nome + ".svg")).read_bytes())
        cores = {e.get("fill") for e in original.iter() if e.get("fill", "").startswith("#") and e.get("fill") not in {"#000", "#000000"}}
        resultado = ET.fromstring(para_fundo_escuro(ET.tostring(original)))
        mantidas = {e.get("fill") for e in resultado.iter()}
        assert cores <= mantidas


def test_traco_monocromatico_fica_claro_sem_filtro_css():
    resultado = para_fundo_escuro(b'<svg xmlns="http://www.w3.org/2000/svg"><path fill="currentColor"/><path fill="#FF7759"/></svg>')
    assert b'#EFE3D2' in resultado and b'#FF7759' in resultado
    css = (Path(__file__).resolve().parents[1] / "src/robinbandit/assets/painel/estilo.css").read_text(encoding="utf-8")
    assert 'filter: invert' not in css
