package com.dsefa.flir;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;

public final class RecordingIndexTest {
    public static void main(String[] args) throws Exception {
        File directory=Files.createTempDirectory("recording-index-test").toFile();
        TimeZone previous=TimeZone.getDefault();
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("GMT+03:00"));
            randomAccessAndNearest(directory);
            rejectsMalformedArchives(directory);
            catalogUsesLocalCaptureDate(directory);
            csvPreservesValuesAndStream(directory);
            System.out.println("PASS archive seeking, validation, local date catalog and streaming CSV");
        } finally {
            TimeZone.setDefault(previous);
            for(File file:directory.listFiles())if(!file.delete())throw new IOException("Cleanup failed: "+file);
            if(!directory.delete())throw new IOException("Cleanup failed: "+directory);
        }
    }
    // Catches wrong frame offsets, unsigned pixel decoding, nearest rounding and shared buffers.
    static void randomAccessAndNearest(File directory) throws Exception {
        File file=archive(directory,"random.raw",new long[]{100,200,200,500},new int[]{123,234,345,65535});
        try(RecordingIndex index=new RecordingIndex(file)) {
            eq(4,index.count(),"frame count");eq(100,index.firstTimestamp(),"first time");eq(500,index.lastTimestamp(),"last time");
            RawArchive.Sample last=index.read(3);eq(65535,last.raw[19199],"unsigned final pixel");eq(500,last.timestamp,"last frame time");
            eq(234,index.read(1).raw[0],"random frame");eq(65535,last.raw[0],"read buffers are independent");
            eq(200,index.timestamp(2),"duplicate time");
            eq(0,index.nearest(Long.MIN_VALUE),"before first");eq(3,index.nearest(Long.MAX_VALUE),"after last");
            eq(0,index.nearest(150),"ties choose earlier");eq(1,index.nearest(200),"duplicate chooses first");eq(3,index.nearest(351),"round toward nearest");
            try {index.read(4);throw new AssertionError("Out of range read accepted");}catch(IndexOutOfBoundsException expected){}
            try {index.timestamp(-1);throw new AssertionError("Negative index accepted");}catch(IndexOutOfBoundsException expected){}
        }
    }
    // Catches silently exporting header-only, truncated or inconsistent recordings.
    static void rejectsMalformedArchives(File directory) throws Exception {
        File empty=archive(directory,"empty.raw",new long[0],new int[0]);reject(empty);
        File corrupt=archive(directory,"corrupt.raw",new long[]{100},new int[]{123});
        try(RandomAccessFile out=new RandomAccessFile(corrupt,"rw")){out.setLength(out.length()-1);}reject(corrupt);
        File badMagic=archive(directory,"magic.raw",new long[]{100},new int[]{123});
        try(RandomAccessFile out=new RandomAccessFile(badMagic,"rw")){out.writeInt(0);}reject(badMagic);
        File badCount=archive(directory,"count.raw",new long[]{100,200},new int[]{123,234});
        try(RandomAccessFile out=new RandomAccessFile(badCount,"rw")){out.seek(4+38412+8);out.writeInt(0);}reject(badCount);
        reject(archive(directory,"reversed.raw",new long[]{200,100},new int[]{123,234}));
    }
    // Catches selecting by filename/UTC and lexicographic rather than capture-time ordering.
    static void catalogUsesLocalCaptureDate(File directory) throws Exception {
        File later=archive(directory,"old-name.raw",new long[]{1704144600000L},new int[]{123}); // Jan 2 00:30 local
        File earlier=archive(directory,"future-name.raw",new long[]{1704141000000L},new int[]{123}); // Jan 1 23:30 local
        File latest=archive(directory,"abc.raw",new long[]{1704148200000L},new int[]{123});
        File[] files={earlier,new File(directory,"missing.raw"),later,latest,new File(directory,"empty.raw")};
        if(!RecordingCatalog.dates(files).equals(Arrays.asList("2024-01-02","2024-01-01")))throw new AssertionError("Wrong local capture dates");
        if(!RecordingCatalog.onDate(files,"2024-01-02").equals(Arrays.asList(latest,later)))throw new AssertionError("Wrong date members/order");
        if(!RecordingCatalog.onDate(files,"2024-02-31").isEmpty())throw new AssertionError("Invalid date accepted");
        if(!RecordingCatalog.dates(null).isEmpty())throw new AssertionError("Null listing should be empty");
    }
    // Catches missing frames, radiometry/unit errors, invalid sampling, and closing caller streams.
    static void csvPreservesValuesAndStream(File directory) throws Exception {
        File file=archive(directory,"comma,file.raw",new long[]{1704144600000L,1704144601000L},new int[]{8000,0});
        Thermal.Settings settings=new Thermal.Settings();settings.emissivity=1;settings.offset=2;
        ByteArrayOutputStream output=new ByteArrayOutputStream(){public void close(){throw new AssertionError("Exporter closed caller stream");}};
        CsvExport.write(file,output,settings,new int[]{0,19199},false,true);
        String[] lines=new String(output.toByteArray(),StandardCharsets.UTF_8).split("\r?\n");
        eq(3,lines.length,"CSV rows");
        if(!lines[0].equals("timestamp_local,timestamp_epoch_ms,unit,min,max,center,P1,P2"))throw new AssertionError("Missing CSV metadata");
        if(!lines[1].startsWith("2024-01-02T00:30:00.000+03:00,1704144600000,F,"))throw new AssertionError("Wrong timestamp/units: "+lines[1]);
        String[] values=lines[1].split(",");
        for(int i=3;i<8;i++)near(223.708,Double.parseDouble(values[i]),.002,"radiometry Fahrenheit");
        if(!lines[2].endsWith(",F,,,,,"))throw new AssertionError("Nonfinite values must be empty: "+lines[2]);
        try {CsvExport.write(file,new ByteArrayOutputStream(),settings,new int[]{19200});throw new AssertionError("Invalid point accepted");}catch(IllegalArgumentException expected){}
        ByteArrayOutputStream averaged=new ByteArrayOutputStream();
        File mixed=archive(directory,"mixed.raw",new long[]{100},new int[]{8000});
        try(RandomAccessFile out=new RandomAccessFile(mixed,"rw")){out.seek(4+12);out.writeShort(9000);}
        CsvExport.write(mixed,averaged,settings,new int[]{0},true,false);
        String[] row=new String(averaged.toByteArray(),StandardCharsets.UTF_8).split("\r?\n")[1].split(",");
        near(109.659,Double.parseDouble(row[6]),.002,"edge average uses four sensor pixels");
        settings.average=true;settings.fahrenheit=true;
        ByteArrayOutputStream selectedSettings=new ByteArrayOutputStream();
        CsvExport.write(mixed,selectedSettings,settings,new int[]{0});
        String[] configured=new String(selectedSettings.toByteArray(),StandardCharsets.UTF_8).split("\r?\n")[1].split(",");
        if(!configured[2].equals("F"))throw new AssertionError("CSV must use selected temperature unit");
        near(229.386,Double.parseDouble(configured[6]),.002,"CSV uses selected averaging");
        if(!CsvExport.field("comma,quote\"\n").equals("\"comma,quote\"\"\n\""))throw new AssertionError("CSV text escaping");
    }
    static File archive(File dir,String name,long[] stamps,int[] values)throws IOException {
        File file=new File(dir,name);
        try(RawArchive.Writer out=new RawArchive.Writer(new FileOutputStream(file))){for(int i=0;i<stamps.length;i++){int[] raw=new int[19200];Arrays.fill(raw,values[i]);out.write(stamps[i],raw);}}
        return file;
    }
    static void reject(File file)throws Exception {try(RecordingIndex ignored=new RecordingIndex(file)){throw new AssertionError("Malformed recording accepted: "+file);}catch(IOException expected){}}
    static void eq(long want,long actual,String message){if(want!=actual)throw new AssertionError(message+": expected "+want+", got "+actual);}
    static void near(double want,double actual,double epsilon,String message){if(!Double.isFinite(actual)||Math.abs(want-actual)>epsilon)throw new AssertionError(message+": expected "+want+", got "+actual);}
}
