"""AzureBlobService: the files of the app in Azure Blob Storage (uploaded tracking files, the positions of each
match, the moment pictures). With an empty connection string the same methods use a local folder
(LOCAL_STORAGE_DIR), so the app runs the same way on a laptop and in the tests."""
import logging
from pathlib import Path

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings

from src.core.settings import settings
from src.core.utils import BadInput, NotFound

logger = logging.getLogger("ApplicationLogger")


class AzureBlobService:
    """
    A class representing Azure Blob Storage service.

    Args:
        connection_string (str): The connection string for the Azure Blob Storage account. Empty: a local folder.
        container_name (str): The name of the container to work with.

    Attributes:
        blob_service_client (BlobServiceClient | None): The BlobServiceClient instance (None when local).
        container_name (str): The name of the container.
        root (Path): The local folder used when there is no connection string.
    """

    def __init__(self, connection_string, container_name):
        self.blob_service_client = None
        self.container_name = container_name
        self.root = Path(settings.local_storage_dir).resolve() / container_name
        if not connection_string:
            return
        try:
            self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
            container_client = self.blob_service_client.get_container_client(container_name)
            if not container_client.exists():
                self.create_container()
        except Exception as e:
            logger.error("Error creating BlobServiceClient for container %s: %s", container_name, e)
            self.blob_service_client = None

    @property
    def source(self) -> str:
        return "azure_blob" if self.blob_service_client else "local"

    def local_path(self, blob_name) -> Path:
        """The local file of a blob name; refuses names that leave the folder."""
        p = (self.root / blob_name).resolve()
        if not p.is_relative_to(self.root) or not blob_name or blob_name.endswith("/"):
            raise BadInput(f"not a file name: {blob_name}")
        return p

    def create_container(self):
        """
        Creates a container in Azure Blob Storage.

        Returns:
            ContainerClient: The ContainerClient instance for the created container.
        """
        if not self.blob_service_client:
            self.root.mkdir(parents=True, exist_ok=True)
            return None
        try:
            if self.container_name in [c["name"] for c in self.blob_service_client.list_containers()]:
                logger.info("Container %s already exists.", self.container_name)
                return self.blob_service_client.get_container_client(self.container_name)
            container_client = self.blob_service_client.create_container(self.container_name)
            logger.info("Container %s created.", self.container_name)
            return container_client
        except Exception as e:
            logger.error("Error creating container %s: %s", self.container_name, e)

    def upload_blob(self, data, filename, content_type=None):
        """
        Uploads a blob to the specified container.

        Args:
            data (bytes): The data to upload.
            filename (str): The name of the blob.
            content_type (str | None): The content type stored with the blob.

        Returns:
            str: The blob name.
        """
        try:
            if not self.blob_service_client:
                p = self.local_path(filename)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
                return filename
            blob_client = self.blob_service_client.get_blob_client(container=self.container_name, blob=filename)
            upload_kwargs = {"blob_type": "BlockBlob", "overwrite": True}
            if content_type is not None:
                upload_kwargs["content_settings"] = ContentSettings(content_type=content_type)
            blob_client.upload_blob(data, **upload_kwargs)
            logger.info("Blob %s uploaded to %s.", filename, self.container_name)
            return filename
        except BadInput:
            raise
        except Exception:
            logger.exception("Error uploading blob %s to %s", filename, self.container_name)
            raise

    def get_blob(self, blob_name):
        """
        Gets the blob from the specified container.

        Args:
            blob_name (str): The name of the blob.

        Returns:
            bytes: The blob.

        Raises:
            NotFound: when there is no such blob.
        """
        if not self.blob_service_client:
            p = self.local_path(blob_name)
            if not p.is_file():
                raise NotFound(f"no file {blob_name}")
            return p.read_bytes()
        blob_client = self.blob_service_client.get_blob_client(container=self.container_name, blob=blob_name)
        try:
            return blob_client.download_blob().readall()
        except ResourceNotFoundError as err:
            raise NotFound(f"no file {blob_name}") from err

    def list_blobs(self, prefix=""):
        """
        Lists the blobs of the current container.

        Args:
            prefix (str): Only blobs whose name starts with this.

        Returns:
            list: A list of {"name", "size"} dicts.
        """
        if not self.blob_service_client:
            if not self.root.exists():
                return []
            return [{"name": str(p.relative_to(self.root)), "size": p.stat().st_size}
                    for p in sorted(self.root.rglob("*")) if p.is_file() and str(p.relative_to(self.root)).startswith(prefix)]
        container_client = self.blob_service_client.get_container_client(self.container_name)
        return [{"name": b.name, "size": b.size} for b in container_client.list_blobs(name_starts_with=prefix)]

    def delete_blob(self, blob_name):
        """
        Deletes a blob from the specified container.

        Args:
            blob_name (str): The name of the blob to delete.

        Returns:
            str: "success".
        """
        try:
            if not self.blob_service_client:
                p = self.local_path(blob_name)
                if not p.is_file():
                    raise NotFound(f"no file {blob_name}")
                p.unlink()
                return "success"
            blob_client = self.blob_service_client.get_blob_client(container=self.container_name, blob=blob_name)
            try:
                blob_client.delete_blob()
            except ResourceNotFoundError as err:
                raise NotFound(f"no file {blob_name}") from err
            logger.info("Blob %s deleted from %s.", blob_name, self.container_name)
            return "success"
        except (NotFound, BadInput):
            raise
        except Exception:
            logger.exception("Error deleting blob %s from %s", blob_name, self.container_name)
            raise

    def delete_blobs_by_prefix(self, prefix):
        """
        Deletes every blob under the given prefix in the current container.

        Args:
            prefix (str): Blob name prefix to delete.

        Returns:
            int: Number of deleted blobs.
        """
        try:
            deleted_count = 0
            for b in self.list_blobs(prefix):
                self.delete_blob(b["name"])
                deleted_count += 1
            logger.info("Deleted %s blobs from %s with prefix %s.", deleted_count, self.container_name, prefix)
            return deleted_count
        except Exception:
            logger.exception("Error deleting blobs from %s with prefix %s", self.container_name, prefix)
            raise


matchFilesBlob = AzureBlobService(
    settings.blob_connection_string,
    settings.blob_container,
)
