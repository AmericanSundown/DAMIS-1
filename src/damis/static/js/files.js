(function() {
	window.files = {
		uploadFile: function(dialog) {
			var url = window.componentFormUrls['UPLOAD FILE'];
			var fileForm = dialog.find(".file-form-container");
			if (fileForm.length == 0) {
                var fileForm = $("<div class=\"file-form-container\"></div>");
                dialog.append(fileForm);
				$.ajax({
					url: url,
					prefix: "",
					context: fileForm  
				}).done(function(resp) {
                    $(this).html(resp);

                    var dialog = $(this).closest(".task-window");
				});
			    window.files.customizeDialog(dialog);
			}
		},

        // upload form in the iframe
        doUpload: function(fileForm) {
            // TODO: clone does not preserve textarea and input values 
            // so we need to construct a placeholder differently 
            var fileFormPlaceholder = fileForm.clone(true);
            var fileUploadForm = $("#file-upload-form");
            // move the fields to the hidden form
            // replace them with a placeholder
            fileForm.after(fileFormPlaceholder).appendTo(fileUploadForm);
            
            $("#file-upload-iframe").off("load");
            $("#file-upload-iframe").on("load", function(resp) {
                window.files.handleUploadResponse(fileFormPlaceholder);
            });
            document.getElementById("file-upload-form").submit();
        },

        // process file upload response
        handleUploadResponse: function(fileFormPlaceholder) {
            var fileUploadIframe = $("#file-upload-iframe"); 
            var textContent = fileUploadIframe.contents().find("body")[0].textContent;

            // if we no text in the iframe, it means that this was not a POST
            // response, so we should exit
            if (!textContent || textContent.length == 0) {
                return;
            }
            var responseText = $("<div class=\"file-form-container\">" + fileUploadIframe.contents().find("body").html() + "</div>");
           
            // clear the iframe response in order to prevent unexpected processing
            fileUploadIframe.contents().find("body").html("");

            // TODO: add saved file id to the OUTPUT_CONNECTION parameter of
            // this task
            $("#file-upload-form").html("");
            fileFormPlaceholder.parent().append(responseText);
            fileFormPlaceholder.remove();
        },

		customizeDialog: function(dialog) {
			var buttons = dialog.dialog("option", "buttons");
			buttons.splice(0, 0, {
				text: gettext('Upload'),
				click: function(ev) {
					var fileForm = $(ev.currentTarget).closest(".ui-dialog").find(".file-form-container");
					window.files.doUpload($(fileForm[0]));
				}
			});
			dialog.dialog("option", "buttons", buttons);
		}
	}
})();
