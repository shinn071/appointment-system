from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


instance = Path(__file__).resolve().parent / "instance"
instance.mkdir(parents=True, exist_ok=True)
ca_cert_path = instance / "campus-clinic-local-ca.cer"
server_cert_path = instance / "localhost-cert.pem"
server_key_path = instance / "localhost-key.pem"

if all(path.exists() for path in (ca_cert_path, server_cert_path, server_key_path)):
    print("A local HTTPS certificate already exists.")
    raise SystemExit(0)

now = datetime.now(timezone.utc)
ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

ca_name = x509.Name([
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Campus Clinic Local Development"),
    x509.NameAttribute(NameOID.COMMON_NAME, "Campus Clinic Local Development CA"),
])
ca_cert = (
    x509.CertificateBuilder()
    .subject_name(ca_name)
    .issuer_name(ca_name)
    .public_key(ca_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - timedelta(minutes=5))
    .not_valid_after(now + timedelta(days=1825))
    .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
    .add_extension(
        x509.KeyUsage(
            digital_signature=True,
            content_commitment=False,
            key_encipherment=False,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=True,
            crl_sign=True,
            encipher_only=False,
            decipher_only=False,
        ),
        critical=True,
    )
    .add_extension(
        x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
        critical=False,
    )
    .sign(ca_key, hashes.SHA256())
)

server_name = x509.Name([
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Campus Clinic Local Development"),
    x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
])
server_cert = (
    x509.CertificateBuilder()
    .subject_name(server_name)
    .issuer_name(ca_cert.subject)
    .public_key(server_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - timedelta(minutes=5))
    .not_valid_after(now + timedelta(days=397))
    .add_extension(
        x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ip_address("127.0.0.1")),
            x509.IPAddress(ip_address("::1")),
        ]),
        critical=False,
    )
    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    .add_extension(
        x509.KeyUsage(
            digital_signature=True,
            content_commitment=False,
            key_encipherment=True,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=False,
            crl_sign=False,
            encipher_only=False,
            decipher_only=False,
        ),
        critical=True,
    )
    .add_extension(
        x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
        critical=False,
    )
    .add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
        critical=False,
    )
    .sign(ca_key, hashes.SHA256())
)

ca_cert_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.DER))
server_cert_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
server_key_path.write_bytes(
    server_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
)
print("Created a localhost-only TLS certificate and private key.")
