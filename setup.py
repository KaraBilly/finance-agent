"""Setup script for finance-agent package.

This script handles the installation and pre-downloads required models.
"""
from setuptools import setup
from setuptools.command.install import install
import subprocess
import sys
import os


class CustomInstallCommand(install):
    """Custom install command that downloads models after installation."""
    
    def run(self):
        # Run standard install
        install.run(self)
        
        # Download models after installation
        print("\n" + "=" * 60)
        print("Finance Agent - Post-Installation")
        print("=" * 60)
        print("\nDownloading embedding models...")
        print("This may take a few minutes on first install.\n")
        
        try:
            # Import and run model downloader
            from finance_agent.download_models import download_all_models
            download_all_models()
        except Exception as e:
            print(f"\n⚠️  Warning: Model download failed: {e}")
            print("   The system will still work with BM25 search.")
            print("   To enable semantic search, run:")
            print("   python -m finance_agent.download_models\n")


# Only use custom install if not building wheel
if __name__ == "__main__":
    # Check if we're building a wheel
    if "bdist_wheel" in sys.argv:
        # Don't download models during wheel build
        setup()
    else:
        # Use custom install command
        setup(
            cmdclass={
                'install': CustomInstallCommand,
            }
        )
