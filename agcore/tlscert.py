"""Eigenes Zertifikat für die Handy-Mikro-Seite.

Handys geben das Mikrofon im Browser nur über https frei. Ein gekauftes Zertifikat gibt es für eine Adresse im
Heimnetz nicht – deshalb stellt SongGrabber sich selbst eins aus (gilt für die IP-Adresse dieses Rechners).
Das Handy zeigt beim ersten Öffnen einmal eine Warnung, danach läuft es.
"""
import datetime
import ipaddress
import os

from . import paths


def ensure(ip):
    """Pfade (cert, key) für diese IP – wird bei Bedarf neu erzeugt. None, wenn es nicht geht."""
    d = os.path.join(paths.data_dir(), "party-tls")
    os.makedirs(d, exist_ok=True)
    cert, key, tag = os.path.join(d, "cert.pem"), os.path.join(d, "key.pem"), os.path.join(d, "ip.txt")
    try:
        if os.path.isfile(cert) and os.path.isfile(key) and open(tag, encoding="utf-8").read().strip() == ip:
            return cert, key
    except OSError:
        pass
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
    except ImportError:
        paths.log.warning("cryptography fehlt – Handy-Mikro (https) nicht verfügbar")
        return None
    k = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"SongGrabber Party {ip}")])
    now = datetime.datetime.now(datetime.timezone.utc)
    san = [x509.DNSName("songgrabber.local")]
    try:
        san.append(x509.IPAddress(ipaddress.ip_address(ip)))
    except ValueError:
        pass
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
         .not_valid_after(now + datetime.timedelta(days=800))
         .add_extension(x509.SubjectAlternativeName(san), critical=False)
         .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
         .sign(k, hashes.SHA256()))
    with open(key, "wb") as f:
        f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with open(cert, "wb") as f:
        f.write(c.public_bytes(serialization.Encoding.PEM))
    with open(tag, "w", encoding="utf-8") as f:
        f.write(ip)
    return cert, key
