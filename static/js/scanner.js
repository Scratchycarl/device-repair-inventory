document.addEventListener('DOMContentLoaded', () => {
    let frontImageData = null;
    let backImageData = null;
    let qrImageData = null;
    let qrParsedData = null;

    const stepIndicator = document.getElementById('step-indicator');
    const lblFront = document.getElementById('lbl-front');
    const inputFront = document.getElementById('input-front');
    const lblBack = document.getElementById('lbl-back');
    const inputBack = document.getElementById('input-back');
    const lblUploadBack = document.getElementById('lbl-upload-back');
    const inputUploadBack = document.getElementById('input-upload-back');
    const lblQr = document.getElementById('lbl-qr');
    const inputQr = document.getElementById('input-qr');
    const lblUploadQr = document.getElementById('lbl-upload-qr');
    const inputUploadQr = document.getElementById('input-upload-qr');
    const btnRetake = document.getElementById('btn-retake');
    const btnSubmit = document.getElementById('btn-submit');
    const previewFront = document.getElementById('preview-front');
    const previewBack = document.getElementById('preview-back');
    const previewQr = document.getElementById('preview-qr');
    const processingDiv = document.getElementById('processing');
    const resultsSection = document.getElementById('results-section');
    const parsedDataDiv = document.getElementById('parsed-data');
    const qrErrorDiv = document.getElementById('qr-error');

    function readFileAsBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = (e) => resolve(e.target.result);
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    function showPreview(container, dataUrl) {
        container.innerHTML = `<img src="${dataUrl}" class="h-full w-full object-cover rounded absolute inset-0">`;
    }

    function showQrCapture() {
        lblFront.classList.add('hidden');
        lblBack.classList.add('hidden');
        lblUploadBack.classList.add('hidden');
        lblQr.classList.remove('hidden');
        lblUploadQr.classList.remove('hidden');
        btnRetake.classList.remove('hidden');
        stepIndicator.innerText = 'Step 3: Snap QR Label (zoom in)';
    }

    async function processQrImage() {
        stepIndicator.innerText = 'Processing...';
        processingDiv.classList.remove('hidden');
        resultsSection.classList.add('hidden');

        try {
            const response = await fetch('/api/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ qr_image: qrImageData })
            });

            const result = await response.json();
            processingDiv.classList.add('hidden');
            resultsSection.classList.remove('hidden');

            if (result.qr_found) {
                qrParsedData = result.parsed;
                stepIndicator.innerText = 'Step 4: Review & Submit';
                parsedDataDiv.classList.remove('hidden');
                qrErrorDiv.classList.add('hidden');
                lblQr.classList.add('hidden');
                lblUploadQr.classList.add('hidden');

                document.getElementById('val-model').innerText = qrParsedData.model || '';
                document.getElementById('val-color').innerText = qrParsedData.color || '';
                document.getElementById('val-capacity').innerText = qrParsedData.capacity || '';
                document.getElementById('val-serial').innerText = qrParsedData.serial_number || '';
                document.getElementById('val-ios').innerText = qrParsedData.ios_version || '';
                document.getElementById('val-imei').innerText = qrParsedData.imei || '';
                document.getElementById('val-battery').innerText = qrParsedData.battery_health || '';
            } else {
                stepIndicator.innerText = 'QR Not Found — try again';
                parsedDataDiv.classList.add('hidden');
                qrErrorDiv.classList.remove('hidden');
                document.getElementById('qr-error-msg').innerText =
                    result.message || 'Could not detect a QR code. Zoom in closer and retake the label photo.';
                qrParsedData = null;
                showQrCapture();
            }
        } catch (error) {
            console.error('Scan error:', error);
            processingDiv.classList.add('hidden');
            resultsSection.classList.remove('hidden');
            parsedDataDiv.classList.add('hidden');
            qrErrorDiv.classList.remove('hidden');
            document.getElementById('qr-error-msg').innerText = 'Server error. Please try again.';
            stepIndicator.innerText = 'Error';
            showQrCapture();
        }
    }

    async function handleBackImage(file) {
        backImageData = await readFileAsBase64(file);
        showPreview(previewBack, backImageData);
        showQrCapture();
    }

    async function handleQrImage(file) {
        qrImageData = await readFileAsBase64(file);
        showPreview(previewQr, qrImageData);
        await processQrImage();
    }

    // Step 1: Front photo
    inputFront.addEventListener('change', async (e) => {
        if (e.target.files.length === 0) return;
        frontImageData = await readFileAsBase64(e.target.files[0]);
        showPreview(previewFront, frontImageData);

        lblFront.classList.add('hidden');
        lblBack.classList.remove('hidden');
        lblUploadBack.classList.remove('hidden');
        btnRetake.classList.remove('hidden');
        stepIndicator.innerText = 'Step 2: Snap Back Photo';
    });

    // Step 2: Back photo (camera / gallery) — used for vision only, not QR
    inputBack.addEventListener('change', async (e) => {
        if (e.target.files.length === 0) return;
        await handleBackImage(e.target.files[0]);
    });

    inputUploadBack.addEventListener('change', async (e) => {
        if (e.target.files.length === 0) return;
        await handleBackImage(e.target.files[0]);
    });

    // Step 3: Zoomed QR label
    inputQr.addEventListener('change', async (e) => {
        if (e.target.files.length === 0) return;
        await handleQrImage(e.target.files[0]);
    });

    inputUploadQr.addEventListener('change', async (e) => {
        if (e.target.files.length === 0) return;
        await handleQrImage(e.target.files[0]);
    });

    btnRetake.addEventListener('click', () => {
        frontImageData = null;
        backImageData = null;
        qrImageData = null;
        qrParsedData = null;
        inputFront.value = '';
        inputBack.value = '';
        inputUploadBack.value = '';
        inputQr.value = '';
        inputUploadQr.value = '';

        previewFront.innerHTML = `<span class="text-xs text-gray-500">Front</span>`;
        previewBack.innerHTML = `<span class="text-xs text-gray-500">Back</span>`;
        previewQr.innerHTML = `<span class="text-xs text-gray-500">QR</span>`;

        lblFront.classList.remove('hidden');
        lblBack.classList.add('hidden');
        lblUploadBack.classList.add('hidden');
        lblQr.classList.add('hidden');
        lblUploadQr.classList.add('hidden');
        btnRetake.classList.add('hidden');
        processingDiv.classList.add('hidden');
        resultsSection.classList.add('hidden');

        stepIndicator.innerText = 'Step 1: Snap Front Photo';
    });

    btnSubmit.addEventListener('click', async () => {
        if (!frontImageData || !backImageData) {
            alert('Please capture both front and back photos first.');
            return;
        }

        btnSubmit.disabled = true;
        btnSubmit.innerText = 'Uploading...';

        const remarks = document.getElementById('custom-remarks').value;
        const payload = {
            ...(qrParsedData || {}),
            remarks: qrParsedData?.raw_qr
                ? `${remarks}\n\nRaw QR: ${qrParsedData.raw_qr}`.trim()
                : remarks,
            front_image: frontImageData,
            back_image: backImageData
        };

        try {
            const response = await fetch('/api/inventory', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const result = await response.json();
            if (response.ok) {
                alert('Device added successfully!');
                window.location.reload();
            } else {
                alert('Error: ' + (result.message || 'Unknown error'));
                btnSubmit.disabled = false;
                btnSubmit.innerText = 'Submit to Inventory';
            }
        } catch (error) {
            console.error('Submit error:', error);
            alert('Failed to connect to server');
            btnSubmit.disabled = false;
            btnSubmit.innerText = 'Submit to Inventory';
        }
    });
});
