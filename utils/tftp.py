import tftpy
import os
import logging
logger = logging.getLogger(__name__)


TFTP_TIMEOUT = 10


def get_device_config_via_tftp(tftp_server=None, device_name=None):
    if not tftp_server or not device_name:
        return

    client = tftpy.TftpClient(tftp_server, 69)
    filenames = [f"{device_name}.cnf.xml", "XMLDefault.cnf.xml"]
    output_dir = os.path.join(os.getcwd(), "downloaded_configs")
    os.makedirs(output_dir, exist_ok=True)
    file_content = ""

    for filename in filenames:
        try:
            dest_path = os.path.join(output_dir, filename)
            logger.info(f"Attempting to fetch {filename} via TFTP...")
            client.download(filename, dest_path, timeout=TFTP_TIMEOUT)
            logger.info(f"Successfully downloaded: {filename}")
            with open(dest_path, "r", encoding="utf-8", errors="ignore") as f:
                file_content = f.read()
                return file_content
        except Exception as e:
            logger.warning(f"[WARN] Failed to fetch {filename}: {e}")

    logger.warning("[WARN] Could not fetch any config file via TFTP.")
    return file_content
