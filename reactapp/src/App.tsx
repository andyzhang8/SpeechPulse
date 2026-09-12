import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { PracticeProvider } from "@/context/practice";
import Setup from "@/pages/Setup";
import Practice from "@/pages/Practice";
import Results from "@/pages/Results";

export default function App() {
  return (
    <PracticeProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Setup />} />
          <Route path="/practice" element={<Practice />} />
          <Route path="/results/:id" element={<Results />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </PracticeProvider>
  );
}
