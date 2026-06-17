# ---------------------------------------------------------------------
        # GEOPTIMALISEERDE STAP 1: TOLERANTERE GEOMETRISCHE DETECTIE
        # ---------------------------------------------------------------------
        blurred = cv2.medianBlur(img_gray, 5)
        # We verlagen param2 van 35 naar 25 (maakt de cirkeldetectie veel flexibeler voor drukwerk)
        circles = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT, dp=1.2, minDist=100,
            param1=50, param2=25, minRadius=20, maxRadius=600
        )
        
        best_crop = None
        detected_x, detected_y, detected_r = 0, 0, 0
        logo_gevonden_geometrisch = False
        
        if circles is not None:
            circles = np.uint16(np.around(circles))
            for i in circles[0, :1]: 
                detected_x, detected_y, detected_r = i[0], i[1], i[2]
                
                marge = int(detected_r * 0.30) # Iets ruimere marge (30%)
                h_img, w_img = img_gray.shape
                ymin = max(0, detected_y - detected_r - marge)
                ymax = min(h_img, detected_y + detected_r + marge)
                xmin = max(0, detected_x - detected_r - marge)
                xmax = min(w_img, detected_x + detected_r + marge)
                
                best_crop = img_np[ymin:ymax, xmin:xmax]
                logo_gevonden_geometrisch = True
                cv2.circle(img_canvas, (detected_x, detected_y), detected_r, (255, 0, 255), 3)

        # ---------------------------------------------------------------------
        # GEOPTIMALISEERDE STAP 2 & 3: MULTI-SCALE MATCHING (MET FALLBACK)
        # ---------------------------------------------------------------------
        logo_status = "MISSING"
        logo_taal = "ONBEKEND"
        logo_variant_detail = ""
        best_match_score = 0.0
        
        # Bepaal de zoekruimte: de crop als die er is, anders de HELE flyer (fallback!)
        search_area_gray = img_gray if best_crop is None else cv2.cvtColor(best_crop, cv2.COLOR_RGB2GRAY)
        
        for variant_naam, ref_img in ref_logos.items():
            ref_gray = cv2.cvtColor(ref_img, cv2.COLOR_RGB2GRAY)
            
            # We scannen nu met een fijnere stapgrootte (0.05) over een breder bereik
            for scale in np.arange(0.2, 2.0, 0.05):
                width = int(ref_gray.shape[1] * scale)
                height = int(ref_gray.shape[0] * scale)
                
                if width > search_area_gray.shape[1] or height > search_area_gray.shape[0]:
                    continue
                    
                resized_ref = cv2.resize(ref_gray, (width, height), interpolation=cv2.INTER_AREA)
                res = cv2.matchTemplate(search_area_gray, resized_ref, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                
                if max_val > best_match_score:
                    best_match_score = max_val
                    logo_variant_detail = variant_naam
                    logo_taal = "NL" if "NL" in variant_naam else "EN"
                    
                    # Als de cirkeldetectie faalde, maar we vinden het logo via de landelijke scan:
                    # bereken dan hier alsnog de coördinaten voor de live preview kaders
                    if not logo_gevonden_geometrisch:
                        detected_x, detected_y = max_loc[0] + width//2, max_loc[1] + height//2
                        detected_r = width//2
                        # Maak alsnog een geldige crop voor de ORB-controle hierna
                        best_crop = img_np[max_loc[1]:max_loc[1]+height, max_loc[0]:max_loc[0]+width]

        # Score-drempel iets realistischer afstellen voor flyers met textuur (0.58)
        if best_match_score >= 0.58: 
            logo_status = "VERMOEDELIJK_OK"
        elif best_match_score >= 0.40:
            logo_status = "AANGEPAST"
        else:
            logo_status = "MISSING"
            
        # Teken achteraf het validatie-kader als de fallback het logo heeft gevonden
        if logo_status == "VERMOEDELIJK_OK" and not logo_gevonden_geometrisch:
            cv2.circle(img_canvas, (detected_x, detected_y), detected_r, (255, 0, 255), 3)
