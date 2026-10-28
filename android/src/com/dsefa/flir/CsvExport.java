package com.dsefa.flir;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.*;

/** Frame-at-a-time export using the radiometry selected when export starts. */
public final class CsvExport {
    private CsvExport(){}
    public static void write(File file,OutputStream output,Thermal.Settings settings,int[] points)throws IOException {
        if(settings==null)throw new IllegalArgumentException("Settings are required");
        write(file,output,settings,points,settings.average,settings.fahrenheit);
    }
    public static void write(File file,OutputStream output,Thermal.Settings settings,int[] points,boolean average,boolean fahrenheit)throws IOException {
        if(output==null||settings==null||points==null)throw new IllegalArgumentException("Output, settings and points are required");
        int[] selected=points.clone();
        for(int point:selected)if(point<0||point>=19200)throw new IllegalArgumentException("Point outside 160x120 sensor: "+point);
        Thermal.Settings snapshot=settings.copy();
        try(RecordingIndex index=new RecordingIndex(file)) {
            // Flush but do not close: the caller owns the document/output stream.
            Writer writer=new BufferedWriter(new OutputStreamWriter(output,StandardCharsets.UTF_8));
            SimpleDateFormat format=new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSSXXX",Locale.US);
            writer.write("timestamp_local,timestamp_epoch_ms,unit,min,max,center");
            for(int i=0;i<selected.length;i++)writer.write(",P"+(i+1));
            writer.write("\r\n");
            for(int frame=0;frame<index.count();frame++) {
                RawArchive.Sample raw=index.read(frame);
                double[] temperatures=Thermal.temperatures(raw.raw,snapshot);
                double min=Double.POSITIVE_INFINITY,max=Double.NEGATIVE_INFINITY;
                for(double value:temperatures)if(Double.isFinite(value)){min=Math.min(min,value);max=Math.max(max,value);}
                writer.write(field(format.format(new Date(raw.timestamp)))+","+raw.timestamp+","+(fahrenheit?"F":"C"));
                value(writer,min,fahrenheit);value(writer,max,fahrenheit);
                value(writer,Thermal.sample(temperatures,60*160+80,average),fahrenheit);
                for(int point:selected)value(writer,Thermal.sample(temperatures,point,average),fahrenheit);
                writer.write("\r\n");
            }
            writer.flush();
        }
    }
    private static void value(Writer output,double celsius,boolean fahrenheit)throws IOException {
        output.write(',');
        if(Double.isFinite(celsius))output.write(String.format(Locale.US,"%.3f",fahrenheit?celsius*1.8+32:celsius));
    }
    static String field(String value) {
        return value.indexOf(',')>=0||value.indexOf('"')>=0||value.indexOf('\r')>=0||value.indexOf('\n')>=0?"\""+value.replace("\"","\"\"")+"\"":value;
    }
}
