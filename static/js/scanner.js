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
    const inputQr = document.getElementById('input-qr');
    const inputUploadQr = document.getElementById('input-upload-qr');
    const inputOcr = document.getElementById('input-ocr');
    const inputUploadOcr = document.getElementById('input-upload-ocr');
    const chkQrCloseup = document.getElementById('chk-qr-closeup');
    const chkOcrLabel = document.getElementById('chk-ocr-label');
    const qrCloseupActions = document.getElementById('qr-closeup-actions');
    const ocrLabelActions = document.getElementById('ocr-label-actions');
    const btnOcrBack = document.getElementById('btn-ocr-back');
    const btnRetake = document.getElementById('btn-retake');
    const btnSubmit = document.getElementById('btn-submit');
    const previewFront = document.getElementById('preview-front');
    const previewBack = document.getElementById('preview-back');
    const previewQrWrap = document.getElementById('preview-qr-wrap');
    const previewQr = document.getElementById('preview-qr');
    const processingDiv = document.getElementById('processing');
    const processingTitle = document.getElementById('processing-title');
    const processingSub = document.getElementById('processing-sub');
    const resultsSection = document.getElementById('results-section');
    const parsedDataDiv = document.getElementById('parsed-data');
    const parsedTitle = document.getElementById('parsed-title');
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

    function fillParsedFields(parsed) {
        document.getElementById('val-model').value = parsed.model || '';
        document.getElementById('val-color').value = parsed.color || '';
        document.getElementById('val-capacity').value = parsed.capacity || '';
        document.getElementById('val-serial').value = parsed.serial_number || '';
        document.getElementById('val-ios').value = parsed.ios_version || '';
        document.getElementById('val-imei').value = parsed.imei || '';
        document.getElementById('val-battery').value = parsed.battery_health || '';
        document.getElementById('val-inv').value = parsed.inventory_number || '';
        document.getElementById('val-date').value = parsed.date_received || '';
        const lockSelect = document.getElementById('val-lock-status');
        lockSelect.value = parsed.lock_status || '';
        styleLockSelect(lockSelect);
        if (parsed.label_notes) {
            const remarks = document.getElementById('custom-remarks');
            if (!remarks.value.trim()) {
                remarks.value = parsed.label_notes;
            }
        }
    }

    function collectParsedFields() {
        const current = qrParsedData || {};
        return {
            ...current,
            model: document.getElementById('val-model').value.trim(),
            color: document.getElementById('val-color').value.trim(),
            capacity: document.getElementById('val-capacity').value.trim(),
            serial_number: document.getElementById('val-serial').value.trim(),
            ios_version: document.getElementById('val-ios').value.trim(),
            imei: document.getElementById('val-imei').value.trim(),
            battery_health: document.getElementById('val-battery').value.trim(),
            inventory_number: document.getElementById('val-inv').value.trim(),
            date_received: document.getElementById('val-date').value.trim(),
            lock_status: document.getElementById('val-lock-status').value,
        };
    }

    function styleLockSelect(select) {
        const blocked = select.value === 'Locked (FMI ON)' || select.value === 'Bypassed';
        select.classList.toggle('bg-red-50', blocked);
        select.classList.toggle('border-red-400', blocked);
        select.classList.toggle('text-red-800', blocked);
        select.classList.toggle('font-semibold', blocked);
    }

    function showParsedSuccess(parsed, title) {
        qrParsedData = parsed;
        stepIndicator.innerText = 'Review & Submit';
        parsedTitle.innerText = title || 'Device Identified';
        parsedDataDiv.classList.remove('hidden');
        qrErrorDiv.classList.add('hidden');
        chkQrCloseup.checked = false;
        chkOcrLabel.checked = false;
        qrCloseupActions.classList.add('hidden');
        ocrLabelActions.classList.add('hidden');
        fillParsedFields(parsed);
    }

    function showQrFailure(message) {
        qrParsedData = null;
        stepIndicator.innerText = 'QR Not Found';
        parsedDataDiv.classList.add('hidden');
        qrErrorDiv.classList.remove('hidden');
        document.getElementById('qr-error-msg').innerText =
            message || 'Could not detect a QR code on the back photo.';
        chkQrCloseup.checked = false;
        chkOcrLabel.checked = false;
        qrCloseupActions.classList.add('hidden');
        ocrLabelActions.classList.add('hidden');
    }

    async function scanImage(imageData, { title, subtitle, payloadKey }) {
        stepIndicator.innerText = 'Processing...';
        processingTitle.innerText = title;
        processingSub.innerText = subtitle;
        processingDiv.classList.remove('hidden');
        resultsSection.classList.add('hidden');

        try {
            const response = await fetch('/api/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [payloadKey]: imageData })
            });

            const result = await response.json();
            processingDiv.classList.add('hidden');
            resultsSection.classList.remove('hidden');

            if (result.qr_found) {
                showParsedSuccess(result.parsed, 'Device Identified');
            } else {
                showQrFailure(result.message);
            }
        } catch (error) {
            console.error('Scan error:', error);
            processingDiv.classList.add('hidden');
            resultsSection.classList.remove('hidden');
            showQrFailure('Server error. Please try again.');
            stepIndicator.innerText = 'Error';
        }
    }

    async function ocrImage(imageData) {
        stepIndicator.innerText = 'Processing...';
        processingTitle.innerText = 'Reading label text...';
        processingSub.innerText = 'Extracting model, serial, battery, and other fields';
        processingDiv.classList.remove('hidden');
        resultsSection.classList.add('hidden');

        try {
            const response = await fetch('/api/ocr', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ label_image: imageData })
            });
            const result = await response.json();
            processingDiv.classList.add('hidden');
            resultsSection.classList.remove('hidden');

            if (result.found && result.parsed) {
                const parsed = result.parsed;
                const now = new Date();
                const yyyy = now.getFullYear();
                const mm = String(now.getMonth() + 1).padStart(2, '0');
                const dd = String(now.getDate()).padStart(2, '0');
                parsed.date_received = `${yyyy}-${mm}-${dd}`;
                showParsedSuccess(parsed, 'Read from Label');
            } else {
                showQrFailure(result.message || 'Could not read the label text.');
                chkOcrLabel.checked = true;
                ocrLabelActions.classList.remove('hidden');
            }
        } catch (error) {
            console.error('OCR error:', error);
            processingDiv.classList.add('hidden');
            resultsSection.classList.remove('hidden');
            showQrFailure('Server error while reading the label.');
            stepIndicator.innerText = 'Error';
            chkOcrLabel.checked = true;
            ocrLabelActions.classList.remove('hidden');
        }
    }

    async function handleBackImage(file) {
        backImageData = await readFileAsBase64(file);
        showPreview(previewBack, backImageData);
        lblBack.classList.add('hidden');
        lblUploadBack.classList.add('hidden');
        await scanImage(backImageData, {
            title: 'Scanning QR code...',
            subtitle: 'Looking for the label on the back photo',
            payloadKey: 'back_image'
        });
    }

    async function handleQrImage(file) {
        qrImageData = await readFileAsBase64(file);
        previewQrWrap.classList.remove('hidden');
        showPreview(previewQr, qrImageData);
        await scanImage(qrImageData, {
            title: 'Reading zoomed QR...',
            subtitle: 'Looking for the QR code in your close-up shot',
            payloadKey: 'qr_image'
        });
    }

    async function handleOcrImage(file) {
        qrImageData = await readFileAsBase64(file);
        previewQrWrap.classList.remove('hidden');
        showPreview(previewQr, qrImageData);
        await ocrImage(qrImageData);
    }

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

    inputBack.addEventListener('change', async (e) => {
        if (e.target.files.length === 0) return;
        await handleBackImage(e.target.files[0]);
    });

    inputUploadBack.addEventListener('change', async (e) => {
        if (e.target.files.length === 0) return;
        await handleBackImage(e.target.files[0]);
    });

    chkQrCloseup.addEventListener('change', () => {
        qrCloseupActions.classList.toggle('hidden', !chkQrCloseup.checked);
    });

    chkOcrLabel.addEventListener('change', () => {
        ocrLabelActions.classList.toggle('hidden', !chkOcrLabel.checked);
    });

    btnOcrBack.addEventListener('click', async () => {
        if (!backImageData) {
            alert('Take a back photo first.');
            return;
        }
        await ocrImage(backImageData);
    });

    inputQr.addEventListener('change', async (e) => {
        if (e.target.files.length === 0) return;
        await handleQrImage(e.target.files[0]);
    });

    inputUploadQr.addEventListener('change', async (e) => {
        if (e.target.files.length === 0) return;
        await handleQrImage(e.target.files[0]);
    });

    inputOcr.addEventListener('change', async (e) => {
        if (e.target.files.length === 0) return;
        await handleOcrImage(e.target.files[0]);
    });

    inputUploadOcr.addEventListener('change', async (e) => {
        if (e.target.files.length === 0) return;
        await handleOcrImage(e.target.files[0]);
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
        inputOcr.value = '';
        inputUploadOcr.value = '';
        chkQrCloseup.checked = false;
        chkOcrLabel.checked = false;
        qrCloseupActions.classList.add('hidden');
        ocrLabelActions.classList.add('hidden');
        const lockSelect = document.getElementById('val-lock-status');
        lockSelect.value = '';
        styleLockSelect(lockSelect);

        previewFront.innerHTML = `<span class="text-xs text-gray-500">Front</span>`;
        previewBack.innerHTML = `<span class="text-xs text-gray-500">Back</span>`;
        previewQr.innerHTML = `<span class="text-xs text-gray-500">QR</span>`;
        previewQrWrap.classList.add('hidden');

        lblFront.classList.remove('hidden');
        lblBack.classList.add('hidden');
        lblUploadBack.classList.add('hidden');
        btnRetake.classList.add('hidden');
        processingDiv.classList.add('hidden');
        resultsSection.classList.add('hidden');

        stepIndicator.innerText = 'Step 1: Snap Front Photo';
    });

    document.getElementById('val-lock-status').addEventListener('change', (e) => {
        styleLockSelect(e.target);
    });

    btnSubmit.addEventListener('click', async () => {
        if (!frontImageData || !backImageData) {
            alert('Please capture both front and back photos first.');
            return;
        }

        btnSubmit.disabled = true;
        btnSubmit.innerText = 'Uploading...';

        const remarks = document.getElementById('custom-remarks').value;
        const parsed = collectParsedFields();
        const extra = parsed.raw_ocr
            ? `\n\nRaw label text:\n${parsed.raw_ocr}`
            : parsed.raw_qr
                ? `\n\nRaw QR: ${parsed.raw_qr}`
                : '';
        const payload = {
            ...parsed,
            remarks: `${remarks}${extra}`.trim(),
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
